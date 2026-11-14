// SES 실행기와 cevsim 엔진 사이의 다리 (docs/ses-platform/16_cevsim_executor.md).
//
// cevsim은 C++ 라이브러리이고 SES 쪽은 Python이다. 이 파일은 cevsim과 함께 하나의 공유
// 라이브러리로 컴파일되어 C 함수 몇 개를 내놓는다. Python은 ctypes로 그 함수를 부른다.
//
// 엔진에 올리는 모델은 두 가지다.
// - Hosted: Python에 있는 모델(공통 모델 기반)을 대신하는 원자 모델. 엔진이 부르는 네 함수를
//   Python으로 넘긴다. 엔진은 일정과 전달만 한다.
// - 고유 모델: ses_cevsim.hpp로 등록한 공장이 만든 cevsim의 원자 모델. 기록을 남길 때는 Tap이
//   감싸서 출력을 Python에 알린다.
//
// cevsim(a9886a6)에서 확인한 엔진의 성질 가운데 이 파일이 맞춰 쓴 것.
// - 일정 목록은 다음 사건 시각만으로 견주는 다중집합이고, 받는 모델을 목록에서 뺄 때 그 시각과
//   같은 모든 항목이 함께 빠진다. 그래서 Hosted는 시간 전진에서 모델마다 다른 아주 작은 값을
//   빼서 다음 사건 시각이 서로 겹치지 않게 한다. 그 값의 크기가 같은 시각 안의 처리 순서도 정한다.
// - 한 번의 출력에서 낸 메시지들은 예약 시각이 같으면 첫째만 전달된다. 그래서 Hosted는
//   메시지마다 예약 시각을 다르게 준다.
// - 엔진은 모델을 가상 소멸자가 없는 바탕 클래스의 포인터로 지운다. 파생 클래스의 소멸자가
//   불리지 않으므로, Hosted와 Tap은 스스로 가진 자원이 없고 모든 자원은 Host가 가진다.

#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "atomic_model.hpp"
#include "executor_factory.hpp"
#include "sim_config.hpp"
#include "system_executor.hpp"

#include "ses_cevsim.hpp"

extern "C" {
typedef long long (*ses_ta_fn)(int id);                                          // 남은 눈금 수. 음수이면 무한
typedef void (*ses_out_fn)(int id);                                              // 낼 포트를 ses_emit으로 알린다
typedef void (*ses_int_fn)(int id);
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

long double Params::number(const std::string& key, long double fallback) const
{
    auto it = values.find(key);
    return it == values.end() ? fallback : std::strtold(it->second.c_str(), nullptr);
}

evsim::Time Params::time(const std::string& key, evsim::Time fallback) const
{
    auto it = values.find(key);
    if (it == values.end())
        return fallback;
    long double v = std::strtold(it->second.c_str(), nullptr);
    return v > evsim::Infinity ? evsim::Infinity : v;
}

// ---------------------------------------------------------------------------
// Host: 엔진 하나와 그 위에 올린 것들
// ---------------------------------------------------------------------------

struct Host
{
    evsim::CSystemExecutor* se = nullptr;
    evsim::CExecutorFactory* ef = nullptr;
    long double step = 1, eps = 0;
    ses_ta_fn ta = nullptr;
    ses_out_fn out = nullptr;
    ses_int_fn internal = nullptr;
    ses_ext_fn ext = nullptr;
    ses_note_fn note = nullptr;

    std::vector<evsim::CModel*> models;                       // 번호에서 엔진에 올린 모델로
    std::vector<std::string> kinds;                           // hosted, native, tapped
    std::vector<evsim::CAtomicModel*> inner;                  // Tap이 감싼 고유 모델. 없으면 nullptr
    std::map<evsim::CModel*, int> ids;                        // 모델(메시지의 출처)에서 번호로
    std::vector<std::vector<std::string>> pending;            // Hosted가 이번 출력에서 낼 포트들
    std::vector<std::map<std::string, evsim::Port*>> ins, outs;
    std::vector<std::unique_ptr<evsim::Port>> ports;          // Hosted의 포트는 여기서 가진다
    std::map<std::string, evsim::Port*> engine_in, engine_out;
    bool started = false;
    int injected = 0;
    std::string text, error;

    void fail(const std::string& what) { if (error.empty()) error = what; }
};

// Python의 모델을 대신하는 원자 모델. 스스로 가진 자원이 없다.
class Hosted : public evsim::CAtomicModel
{
public:
    Hosted(Host* host, int id, const std::string& name, long double units)
        : evsim::CAtomicModel(name), host(host), id(id), units(units) {}

    void external_transition(evsim::Port& port, evsim::Message& msg) override
    {
        auto src = host->ids.find(msg->get_source());
        host->ext(id, port.m_name.c_str(), src == host->ids.end() ? -1 : src->second, msg->get_out_port()->m_name.c_str());
    }

    void internal_transition() override { host->internal(id); }

    void output_function(evsim::MessageDeliverer& deliverer) override
    {
        std::vector<std::string>& names = host->pending[id];
        names.clear();
        host->out(id);
        int k = 0;
        for (const std::string& name : names)
        {
            auto port = host->outs[id].find(name);
            if (port == host->outs[id].end())
            {
                host->fail("출력 포트가 없다: " + get_name().m_name + "." + name);
                continue;
            }
            // 예약 시각이 같은 메시지는 첫째만 전달된다. 메시지마다 다른 시각을 준다
            deliverer.insert_message(create_message(*port->second, (evsim::Time)(k++) * 1e-9L));
        }
    }

    evsim::Time time_advance() override
    {
        long long ticks = host->ta(id);
        if (ticks < 0)
            return evsim::Infinity;
        // 다음 사건 시각이 다른 모델과 겹치지 않게 모델마다 다른 값을 뺀다
        return (long double)ticks * host->step - units * host->eps;
    }

private:
    Host* host;
    int id;
    long double units;
};

// 고유 모델을 감싸 출력을 알린다. 포트는 안쪽 모델의 것을 그대로 쓴다.
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
        if (model->is_cancel_reschedule())                    // 엔진은 올려진 모델의 표시를 본다
        {
            set_cancel_reschedule(true);
            model->set_cancel_reschedule(false);
        }
    }

    void internal_transition() override { model->internal_transition(); }

    void output_function(evsim::MessageDeliverer& deliverer) override
    {
        model->output_function(deliverer);
        for (const evsim::Message& m : deliverer.get_contents())
            host->note(id, m->get_out_port()->m_name.c_str());
    }

    evsim::Time time_advance() override { return model->time_advance(); }

private:
    Host* host;
    int id;
    evsim::CAtomicModel* model;
};

// 엔진이 가진 것을 읽는다. 등록된 모델의 목록에는 공개된 접근자가 없어 보호 멤버를 읽는다.
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

static int enroll(Host* host, evsim::CModel* model, const char* kind, evsim::CAtomicModel* inner)
{
    int id = (int)host->models.size();
    host->models.push_back(model);
    host->kinds.push_back(kind);
    host->inner.push_back(inner);
    host->pending.emplace_back();
    host->ins.emplace_back();
    host->outs.emplace_back();
    host->ids[model] = id;
    if (inner)
        host->ids[inner] = id;
    return id;
}

}   // namespace ses

using ses::Host;

extern "C" {

void* ses_new(double step, double eps, ses_ta_fn ta, ses_out_fn out, ses_int_fn internal, ses_ext_fn ext, ses_note_fn note)
{
    Host* host = new Host();
    host->step = step;
    host->eps = eps;
    host->ta = ta;
    host->out = out;
    host->internal = internal;
    host->ext = ext;
    host->note = note;
    host->ef = new evsim::CExecutorFactory();
    evsim::SimConfig config;
    config.engine_name = "ses";
    config.time_resolution = step;
    config.execution_mode = evsim::BLOCKING;
    config.simulation_mode = evsim::VIRTUAL;                  // 실제 시간에 맞춰 쉬지 않는다
    config.ef = host->ef;
    host->se = evsim::CSystemExecutor::create_system_executor(config, "ses");
    return host;
}

void ses_free(void* handle)
{
    Host* host = (Host*)handle;
    if (!host->started)                                       // 엔진은 실행을 시작할 때 모델을 넘겨받는다
        for (evsim::CModel* model : host->models)
            delete dynamic_cast<evsim::CAtomicModel*>(model);
    for (evsim::CAtomicModel* model : host->inner)
        delete model;
    delete host->se;
    delete host->ef;
    delete host;
}

// Python의 모델을 올린다. 포트 이름은 줄바꿈으로 나눈다. units는 다음 사건 시각에서 뺄 값의 배수다.
int ses_add_hosted(void* handle, const char* name, const char* ins, const char* outs, double units)
{
    Host* host = (Host*)handle;
    int id = (int)host->models.size();
    ses::Hosted* model = new ses::Hosted(host, id, name, units);
    ses::enroll(host, model, "hosted", nullptr);
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
    int id = (int)host->models.size();
    if (tap)
        ses::enroll(host, new ses::Tap(host, id, model), "tapped", model);
    else
        ses::enroll(host, model, "native", nullptr);
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
    host->se->insert_coupling(src < 0 ? host->se : host->models[src], *a, dst < 0 ? host->se : host->models[dst], *b);
    return 0;
}

// 엔진의 경계로 밖에서 입력을 넣는다. at은 전달할 시각이다. cevsim의 메시지에는 값이 없다.
int ses_inject(void* handle, const char* port, double at)
{
    Host* host = (Host*)handle;
    auto it = host->engine_in.find(port);
    if (it == host->engine_in.end())
        return -1;
    // 예약 시각이 같은 외부 입력은 첫째만 전달된다. 입력마다 시각을 아주 조금씩 앞당겨 서로 다르게 한다
    evsim::Time when = (evsim::Time)at - (evsim::Time)(++host->injected) * 1e-9L;
    host->se->insert_external_event(host->se->create_message(*it->second, when));
    return 0;
}

// Hosted의 출력 함수 안에서 Python이 부른다.
void ses_emit(void* handle, int id, const char* port)
{
    Host* host = (Host*)handle;
    if (id >= 0 && id < (int)host->pending.size())
        host->pending[id].push_back(port);
}

// span만큼 더 돌린다. cevsim의 simulate는 현재 시각에서 span 뒤까지의 눈금을 끝을 포함해 처리한다.
int ses_run(void* handle, double span)
{
    Host* host = (Host*)handle;
    if (host->models.empty())
        return 0;
    host->started = true;
    try
    {
        host->se->simulate((evsim::Time)span);
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
// 모델과 결합은 엔진의 자료에서, 포트는 모델 객체에서 읽는다.
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
    for (const evsim::Message& m : se.get_external_output_deliverer().get_contents())
    {
        auto src = host->ids.find(m->get_source());                       // 경계의 어느 포트로 나갔는지는 엔진에 남지 않는다
        out << "O\t" << (src == host->ids.end() ? -1 : src->second) << "\t" << m->get_out_port()->m_name << "\n";
    }
    host->text = out.str();
    return host->text.c_str();
}

}   // extern "C"
