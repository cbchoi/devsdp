// SES 실행기와 cevsim 엔진 사이의 다리 (docs/ses-platform/16_cevsim_executor.md).
//
// cevsim은 C++ 라이브러리이고 SES 쪽은 Python이다. 이 파일은 cevsim과 함께 하나의 공유
// 라이브러리로 컴파일되어 C 함수 몇 개를 내놓는다. Python은 ctypes로 그 함수를 부른다.
//
// 엔진에 올리는 모델은 두 가지다.
// - Hosted: Python에 있는 모델(공통 모델 기반)을 대신하는 원자 모델. 엔진이 부르는 함수를
//   Python으로 넘긴다. 엔진은 일정과 전달만 한다.
// - 고유 모델: ses_cevsim.hpp로 등록한 공장이 만든 cevsim의 원자 모델. 기록을 남길 때는 Tap이
//   감싸서 출력을 Python에 알린다.
//
// cevsim의 main(45e7fa9)에 맞췄다. 이 파일이 기대는 엔진의 성질은 다음과 같다.
// - 사건 시각은 정확한 값 그대로다. 시간 격자가 없다. 음수인 시간 전진은 예외가 된다.
// - 같은 시각의 모델은 모델 번호의 순서, 곧 만든 순서로 하나씩 처리된다.
// - 엔진은 모델이 메시지를 받거나 차례를 마칠 때마다 그 모델의 시간 전진을 다시 묻는다.
// - 엔진은 등록한 모델을 넘겨받아 스스로 지운다.
//
// 공통 모델의 시각을 눈금으로 세는 일은 Python 쪽이 한다. 엔진의 시계는 모델의 시간(초 등)을 그대로 쓴다.
// 이 파일은 엔진의 시각을 알려 주고, 공통 모델의 다음 사건 시각까지 엔진을 돌리는 일만 거든다.

#include <cstdio>
#include <cstdlib>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "atomic_model.hpp"
#include "executor_factory.hpp"
#include "sim_config.hpp"
#include "system_executor.hpp"

#include "ses_cevsim.hpp"

extern "C" {
typedef double (*ses_ta_fn)(int id);                                             // 다음 사건까지 남은 시간. 음수이면 무한
typedef void (*ses_out_fn)(int id);                                              // 낼 포트를 ses_emit으로 알린다
typedef void (*ses_ext_fn)(int id, const char* port, int src, const char* src_port);
typedef void (*ses_note_fn)(int id, const char* port);                           // 고유 모델이 낸 메시지 하나
}

namespace ses {

// ---------------------------------------------------------------------------
// 고유 모델의 등록부
// ---------------------------------------------------------------------------

static std::map<std::string, Factory>& registry()
{
    static std::map<std::string, Factory> modules;
    return modules;
}

bool add_module(const std::string& module, Factory factory)
{
    registry()[module] = factory;
    return true;
}

std::string Params::text(const std::string& key, const std::string& fallback) const
{
    auto it = values.find(key);
    return it == values.end() ? fallback : it->second;
}

// 수는 배정밀도로 읽는다. 계획에 적힌 값이 배정밀도이고, 글자는 그 값으로 정확히 되돌아가게 적혀 온다.
// long double로 읽으면 0.1 같은 값이 계획의 값과 끝자리가 다른 수가 되고, 그 차이가 플랫폼마다 다르다.
long double Params::number(const std::string& key, long double fallback) const
{
    auto it = values.find(key);
    return it == values.end() ? fallback : std::strtod(it->second.c_str(), nullptr);
}

evsim::Time Params::time(const std::string& key, evsim::Time fallback) const
{
    auto it = values.find(key);
    if (it == values.end())
        return fallback;
    double v = std::strtod(it->second.c_str(), nullptr);
    return v > evsim::Infinity ? evsim::Infinity : v;
}

// ---------------------------------------------------------------------------
// Host: 엔진 하나와 그 위에 올린 것들
// ---------------------------------------------------------------------------

struct Delivered                                              // 엔진의 경계로 나간 출력 하나
{
    evsim::Time at;
    std::string port;
    int from;
};

struct Host
{
    evsim::CSystemExecutor* se = nullptr;
    evsim::CExecutorFactory* ef = nullptr;
    ses_ta_fn ta = nullptr;
    ses_out_fn out = nullptr;
    ses_ext_fn ext = nullptr;
    ses_note_fn note = nullptr;

    std::vector<evsim::CModel*> models;                       // 번호에서 엔진에 올린 모델로. 모델은 엔진이 가진다
    std::vector<std::string> kinds;                           // hosted, native, tapped
    std::map<evsim::CModel*, int> ids;                        // 모델(메시지의 출처)에서 번호로. Tap이 감싼 모델도 든다
    std::vector<std::vector<std::string>> pending;            // Hosted가 이번 출력에서 낼 포트들
    std::vector<std::map<std::string, evsim::Port*>> ins, outs;
    std::vector<std::unique_ptr<evsim::Port>> ports;          // Hosted의 포트는 여기서 가진다
    std::map<std::string, evsim::Port*> engine_in, engine_out;
    std::vector<Delivered> delivered;
    int emitter = -1;                                         // 지금 출력을 내고 있는 모델. 모르면 -1
    std::string text, error;

    void fail(const std::string& what) { if (error.empty()) error = what; }
};

// Python의 모델을 대신하는 원자 모델.
class Hosted : public evsim::CAtomicModel
{
public:
    Hosted(Host* host, int id, const std::string& name) : evsim::CAtomicModel(name), host(host), id(id) {}

    void external_transition(evsim::Port& port, evsim::Message& msg) override
    {
        auto src = host->ids.find(msg->get_source());
        host->ext(id, port.m_name.c_str(), src == host->ids.end() ? -1 : src->second, msg->get_out_port()->m_name.c_str());
    }

    // 전이는 전이 신호를 받았을 때 Python에서 한다. 여기서는 출력의 전달이 끝났음만 적는다.
    // 이 뒤에 기록하지 않는 고유 모델이 경계로 낸 것을 이 모델이 낸 것으로 적지 않기 위해서다
    void internal_transition() override { host->emitter = -1; }

    void output_function(evsim::MessageDeliverer& deliverer) override
    {
        std::vector<std::string>& names = host->pending[id];
        names.clear();
        host->emitter = id;
        host->out(id);
        for (const std::string& name : names)                 // 메시지는 만든 순서대로 전달된다
        {
            auto port = host->outs[id].find(name);
            if (port == host->outs[id].end())
            {
                host->fail("출력 포트가 없다: " + get_name().m_name + "." + name);
                continue;
            }
            deliverer.insert_message(create_message(*port->second));
        }
    }

    // 엔진은 이 모델이 메시지를 받거나 차례를 마칠 때마다 묻는다. 답은 Python이 가진 눈금에서 나온다
    evsim::Time time_advance() override
    {
        double left = host->ta(id);
        return left < 0 ? evsim::Infinity : (evsim::Time)left;
    }

private:
    Host* host;
    int id;
};

// 고유 모델을 감싸 출력을 알린다. 포트는 안쪽 모델의 것을 그대로 쓴다. 안쪽 모델은 Tap이 가진다.
class Tap : public evsim::CAtomicModel
{
public:
    Tap(Host* host, int id, evsim::CAtomicModel* model)
        : evsim::CAtomicModel(model->get_name().m_name), host(host), id(id), model(model)
    {
        for (evsim::Port* p : model->in_port())
            register_input_port(*p);
        for (evsim::Port* p : model->out_port())
            register_output_port(*p);
    }

    void external_transition(evsim::Port& port, evsim::Message& msg) override
    {
        model->external_transition(port, msg);
        pass();
    }

    void external_value_transition(evsim::Port& port, const evsim::ValueMessage& msg) override
    {
        model->external_value_transition(port, msg);
        pass();
    }

    void internal_transition() override
    {
        model->internal_transition();
        pass();
    }

    void output_function(evsim::MessageDeliverer& deliverer) override
    {
        host->emitter = id;
        mine.emplace();                                       // 안쪽 모델이 낸 것을 먼저 받아 적고 엔진에 넘긴다
        model->output_function(*mine);
        while (mine->has_contents())
        {
            if (mine->has_values())                           // 값 메시지: 값은 그대로 넘기고 포트만 알린다
            {
                evsim::ValueSelection v = mine->first_value();
                host->note(id, v.message.get_out_port()->m_name.c_str());
                deliverer.insert_value(v.message);
                mine->value_delivered(v.token);
            }
            else
            {
                evsim::Message m = mine->first_message();
                host->note(id, m->get_out_port()->m_name.c_str());
                deliverer.insert_message(m);
                mine->message_delivered(m);
            }
        }
    }

    evsim::Time time_advance() override
    {
        evsim::Time left = model->time_advance();
        pass();
        return left;
    }

private:
    void pass()                                               // 엔진은 올려진 모델의 표시를 본다
    {
        if (model->is_cancel_reschedule())
        {
            set_cancel_reschedule(true);
            model->set_cancel_reschedule(false);
        }
    }

    Host* host;
    int id;
    std::unique_ptr<evsim::CAtomicModel> model;
    std::optional<evsim::MessageDeliverer> mine;
};

// 엔진이 가진 것을 읽는다. 등록된 모델의 목록과 일정에는 공개된 접근자가 없어 보호 멤버를 읽는다.
struct Peek : evsim::CSystemExecutor
{
    static std::multiset<evsim::create_constraint>& waiting(evsim::CSystemExecutor& s) { return s.*(&Peek::m_wait_object_list); }
    static std::map<evsim::CModel*, evsim::IExecutor>& live(evsim::CSystemExecutor& s) { return s.*(&Peek::m_model_executor_map); }
};

static std::vector<std::string> split(const char* text)
{
    std::vector<std::string> out;
    std::stringstream stream(text ? text : "");
    std::string line;
    while (std::getline(stream, line))
        if (!line.empty())
            out.push_back(line);
    return out;
}

static evsim::Port* find_port(Host* host, int id, const std::string& name, bool input)
{
    if (id < 0)
    {
        auto& table = input ? host->engine_in : host->engine_out;
        auto it = table.find(name);
        return it == table.end() ? nullptr : it->second;
    }
    auto& table = input ? host->ins[id] : host->outs[id];
    auto it = table.find(name);
    return it == table.end() ? nullptr : it->second;
}

static int enroll(Host* host, evsim::CModel* model, const char* kind)
{
    int id = (int)host->models.size();
    host->models.push_back(model);
    host->kinds.push_back(kind);
    host->pending.emplace_back();
    host->ins.emplace_back();
    host->outs.emplace_back();
    host->ids[model] = id;
    return id;
}

}   // namespace ses

using ses::Host;

extern "C" {

void* ses_new(ses_ta_fn ta, ses_out_fn out, ses_ext_fn ext, ses_note_fn note)
{
    Host* host = new Host();
    host->ta = ta;
    host->out = out;
    host->ext = ext;
    host->note = note;
    host->ef = new evsim::CExecutorFactory();
    evsim::SimConfig config;
    config.engine_name = "ses";
    config.execution_mode = evsim::BLOCKING;
    config.simulation_mode = evsim::VIRTUAL;                  // 실제 시간에 맞춰 쉬지 않는다
    config.backend = evsim::ExecutionBackend::Hierarchical;   // 모델마다 실행기를 하나씩 두는 방식
    config.ef = host->ef;
    host->se = evsim::CSystemExecutor::create_system_executor(config, "ses");
    // 엔진의 경계로 나간 출력을 받아 적는다. 엔진이 넘기는 메시지에는 경계의 포트만 있고 시각과 낸 모델이 없다
    host->se->set_output_handler([host](evsim::Message m) {
        host->delivered.push_back({host->se->get_global_time(), m->get_out_port()->m_name, host->emitter});
    });
    return host;
}

void ses_free(void* handle)
{
    Host* host = (Host*)handle;
    delete host->se;                                          // 엔진이 모델을 지운다. 포트와 공장은 그 뒤에 지운다
    delete host->ef;
    delete host;
}

// Python의 모델을 올린다. 포트 이름은 줄바꿈으로 나눈다.
int ses_add_hosted(void* handle, const char* name, const char* ins, const char* outs)
{
    Host* host = (Host*)handle;
    int id = (int)host->models.size();
    ses::Hosted* model = new ses::Hosted(host, id, name);
    ses::enroll(host, model, "hosted");
    for (const std::string& p : ses::split(ins))
    {
        host->ports.emplace_back(new evsim::Port(p));
        host->ins[id][p] = host->ports.back().get();
        model->register_input_port(*host->ports.back());
    }
    for (const std::string& p : ses::split(outs))
    {
        host->ports.emplace_back(new evsim::Port(p));
        host->outs[id][p] = host->ports.back().get();
        model->register_output_port(*host->ports.back());
    }
    host->se->register_entity(model, 0, evsim::Infinity);
    return id;
}

// 등록된 공장으로 고유 모델을 만들어 올린다. params는 "이름=값"을 줄바꿈으로 나눈 것이다.
int ses_add_native(void* handle, const char* module, const char* name, const char* params, int tap)
{
    Host* host = (Host*)handle;
    auto factory = ses::registry().find(module);
    if (factory == ses::registry().end())
    {
        host->fail(std::string("등록되지 않은 모듈이다: ") + module);
        return -1;
    }
    ses::Params p;
    for (const std::string& line : ses::split(params))
    {
        size_t eq = line.find('=');
        if (eq != std::string::npos)
            p.values[line.substr(0, eq)] = line.substr(eq + 1);
    }
    evsim::CAtomicModel* model = nullptr;
    try
    {
        model = factory->second(name, p);
    }
    catch (const std::exception& e)
    {
        host->fail(std::string("모듈의 공장이 실패했다: ") + module + ": " + e.what());
        return -1;
    }
    if (model == nullptr)
    {
        host->fail(std::string("모듈의 공장이 모델을 만들지 않았다: ") + module);
        return -1;
    }
    if (host->ids.count(model))                               // 엔진과 Tap이 모델을 넘겨받으므로 한 모델을 두 번 올릴 수 없다
    {
        host->fail(std::string("모듈의 공장이 같은 모델을 두 번 내놓았다: ") + module);
        return -1;
    }
    int id = (int)host->models.size();
    ses::enroll(host, tap ? new ses::Tap(host, id, model) : model, tap ? "tapped" : "native");
    host->ids[model] = id;
    for (evsim::Port* port : model->in_port())
        host->ins[id][port->m_name] = port;
    for (evsim::Port* port : model->out_port())
        host->outs[id][port->m_name] = port;
    host->se->register_entity(host->models[id], 0, evsim::Infinity);
    return id;
}

// 엔진의 경계에 포트를 둔다. 계획의 뿌리의 포트다.
int ses_add_port(void* handle, const char* name, int input)
{
    Host* host = (Host*)handle;
    auto& table = input ? host->engine_in : host->engine_out;
    if (table.count(name))
        return -1;
    table[name] = input ? &host->se->create_input_port(name) : &host->se->create_output_port(name);
    return 0;
}

// 결합 하나를 엔진에 등록한다. 번호가 음수이면 엔진의 경계다.
int ses_couple(void* handle, int src, const char* src_port, int dst, const char* dst_port)
{
    Host* host = (Host*)handle;
    int count = (int)host->models.size();
    if (src >= count || dst >= count || (src < 0 && dst < 0))
        return -1;
    evsim::Port* a = ses::find_port(host, src, src_port, src < 0);       // 경계의 입력 포트가 출발점이다
    evsim::Port* b = ses::find_port(host, dst, dst_port, dst >= 0);      // 경계의 출력 포트가 도착점이다
    if (a == nullptr || b == nullptr)
        return -2;
    try
    {
        host->se->insert_coupling(src < 0 ? host->se : host->models[src], *a, dst < 0 ? host->se : host->models[dst], *b);
    }
    catch (const std::exception& e)                           // 값 포트와 값 없는 포트를 이으면 엔진이 거절한다
    {
        host->fail(std::string("엔진이 결합을 거절했다: ") + e.what());
        return -3;
    }
    return 0;
}

// 엔진의 경계로 밖에서 입력을 넣는다. at은 전달할 시각이다. 이 메시지에는 값이 없다.
// snap이면 엔진의 시각보다 앞선 at을 엔진의 시각으로 올린다. 같은 눈금 안의 끝자리 차이를 지금의 입력으로 받기 위해서다.
int ses_inject(void* handle, const char* port, double at, int snap)
{
    Host* host = (Host*)handle;
    auto it = host->engine_in.find(port);
    if (it == host->engine_in.end())
        return -1;
    evsim::Time when = (evsim::Time)at, now = host->se->get_global_time();
    if (snap && when < now)
        when = now;
    try
    {
        host->se->insert_external_event(host->se->create_message(*it->second, when));
    }
    catch (const std::exception&)                             // 이미 지난 시각이거나 유한한 수가 아니다
    {
        return -2;
    }
    return 0;
}

// Hosted의 출력 함수 안에서 Python이 부른다.
void ses_emit(void* handle, int id, const char* port)
{
    Host* host = (Host*)handle;
    if (id >= 0 && id < (int)host->pending.size())
        host->pending[id].push_back(port);
}

// 실행을 멈추게 한다. 엔진은 처리하던 사건을 마치고 돌아온다.
void ses_stop(void* handle)
{
    ((Host*)handle)->se->stop();
}

static int advance(Host* host, evsim::Time span)
{
    try
    {
        host->se->simulate(span);
    }
    catch (const std::exception& e)
    {
        host->fail(std::string("실행 중의 예외: ") + e.what());
    }
    return host->error.empty() ? 0 : -1;
}

// 시각 until까지 돌린다. 그 시각의 사건도 처리한다. 이미 지난 시각이면 아무것도 하지 않는다.
// 다만 flush이면 지금 시각에 남은 사건은 처리한다. until과 지금 시각이 같은 눈금일 때 쓴다.
int ses_run(void* handle, double until, int flush)
{
    Host* host = (Host*)handle;
    if (!host->error.empty())
        return -1;
    evsim::Time now = host->se->get_global_time(), goal = (evsim::Time)until;
    if (!(goal >= now))
        return flush ? advance(host, 0) : 0;
    // 엔진은 지금 시각에 이 값을 더한 시각까지 돌린다. goal이 배정밀도 수이면 그 합은 goal과 정확히 같다
    return advance(host, goal - now);
}

// 엔진의 다음 사건 시각 하나를 처리한다. 공통 모델의 사건 시각은 엔진이 더해서 정한 값이라 눈금의 시각과
// 끝자리가 다를 수 있다. 그래서 정한 시각까지가 아니라 "다음 사건까지" 돌리는 길을 따로 둔다.
int ses_step(void* handle)
{
    Host* host = (Host*)handle;
    if (!host->error.empty())
        return -1;
    try
    {
        if (host->se->schedule() >= evsim::Infinity)
            host->fail("엔진의 일정에 남은 사건이 없다");
    }
    catch (const std::exception& e)
    {
        host->fail(std::string("실행 중의 예외: ") + e.what());
    }
    return host->error.empty() ? 0 : -1;
}

double ses_time(void* handle)
{
    return (double)((Host*)handle)->se->get_global_time();
}

const char* ses_last_error(void* handle)
{
    return ((Host*)handle)->error.c_str();
}

// 등록된 모듈의 이름들.
const char* ses_modules()
{
    static std::string text;
    text.clear();
    for (auto& entry : ses::registry())
        text += entry.first + "\n";
    return text.c_str();
}

// 엔진이 가진 것을 글로 내놓는다: 모델(M), 포트(P), 결합(C), 경계로 나간 출력(O). 번호 -1은 엔진의 경계다.
// 모델과 결합은 엔진의 자료에서, 포트는 모델 객체에서 읽는다. 경계로 나간 출력은 엔진이 넘겨준 것을 적어 둔 것이다.
const char* ses_dump(void* handle)
{
    Host* host = (Host*)handle;
    evsim::CSystemExecutor& se = *host->se;
    std::ostringstream out;
    std::map<evsim::Port*, std::pair<int, std::string>> owner;

    std::vector<evsim::CModel*> held;
    for (const evsim::create_constraint& c : ses::Peek::waiting(se))
        held.push_back(c.p_model);
    for (auto& entry : ses::Peek::live(se))
        held.push_back(entry.first);
    for (evsim::CModel* model : held)
    {
        auto it = host->ids.find(model);
        if (it == host->ids.end())
        {
            out << "X\t" << model->get_name().m_name << "\n";             // 다리가 올리지 않은 모델
            continue;
        }
        int id = it->second;
        out << "M\t" << id << "\t" << host->kinds[id] << "\t" << model->get_name().m_name << "\n";
        for (evsim::Port* p : model->in_port())
        {
            out << "P\t" << id << "\tin\t" << p->m_name << "\n";
            owner[p] = {id, p->m_name};
        }
        for (evsim::Port* p : model->out_port())
        {
            out << "P\t" << id << "\tout\t" << p->m_name << "\n";
            owner[p] = {id, p->m_name};
        }
    }
    for (evsim::Port* p : se.in_port())
    {
        out << "P\t-1\tin\t" << p->m_name << "\n";
        owner[p] = {-1, p->m_name};
    }
    for (evsim::Port* p : se.out_port())
    {
        out << "P\t-1\tout\t" << p->m_name << "\n";
        owner[p] = {-1, p->m_name};
    }
    const char* kinds[3] = {"eic", "ic", "eoc"};
    std::map<evsim::Port*, std::vector<evsim::Port*>>* maps[3] = {&se.get_eic(), &se.get_ic(), &se.get_eoc()};
    for (int k = 0; k < 3; k++)
        for (auto& entry : *maps[k])
            for (evsim::Port* dst : entry.second)
            {
                auto a = owner.find(entry.first), b = owner.find(dst);
                if (a == owner.end() || b == owner.end())
                {
                    out << "X\t" << kinds[k] << "\n";                     // 어느 모델의 것도 아닌 포트
                    continue;
                }
                out << "C\t" << kinds[k] << "\t" << a->second.first << "\t" << a->second.second << "\t"
                    << b->second.first << "\t" << b->second.second << "\n";
            }
    for (const ses::Delivered& d : host->delivered)
    {
        char at[40];
        std::snprintf(at, sizeof at, "%.17g", (double)d.at);
        out << "O\t" << at << "\t" << d.port << "\t" << d.from << "\n";
    }
    host->text = out.str();
    return host->text.c_str();
}

}   // extern "C"
