// cevsim 엔진에서 확인한 성질을 다시 실행해 보는 프로그램 (docs/ses-platform/16_cevsim_executor.md 2절).
// tests/test_cevsim.py가 컴파일해 돌리고, 줄마다 적힌 "이름 값"을 기대값과 견준다.
// cevsim의 main(45e7fa9)에서 확인했다. 앞선 커밋(a9886a6)에서의 값은 16 문서의 표에 있다.
// 엔진이 바뀌면 이 프로그램의 출력이 먼저 달라진다.
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "atomic_model.hpp"
#include "coupled_model.hpp"
#include "executor_factory.hpp"
#include "sim_config.hpp"
#include "system_executor.hpp"
#include "value_message.hpp"

using namespace evsim;

static std::vector<std::string> LOG;                         // "모델@시각"
static CSystemExecutor* ENGINE = nullptr;
static int DESTROYED = 0;

static std::string at(const std::string& who)
{
    std::ostringstream s;
    s << who << "@" << (double)ENGINE->get_global_time();
    return s.str();
}

// 주기마다 out으로 낸다. twice이면 out2로도 낸다. 받은 수를 센다. keep이면 입력을 받아도 다음 사건 시각을 지킨다.
// reverse이면 out2의 메시지를 먼저 만든다.
class Tick : public CAtomicModel
{
public:
    Tick(std::string name, Time period, bool keep = false, bool twice = false, bool reverse = false)
        : CAtomicModel(name), run("RUN", period), n(0), got(0), keep(keep), twice(twice), reverse(reverse)
    {
        REGISTER_INPUT_PORT(inp);
        REGISTER_OUTPUT_PORT(out);
        REGISTER_OUTPUT_PORT(out2);
        set_current_state(&run);
    }
    ~Tick() override { DESTROYED++; }
    void external_transition(Port&, Message&) override
    {
        got++;
        LOG.push_back(at("ext-" + get_name().m_name));
        if (keep)
            set_cancel_reschedule(true);
    }
    void internal_transition() override { n++; }
    void output_function(MessageDeliverer& d) override
    {
        LOG.push_back(at(get_name().m_name));
        if (reverse)
            d.insert_message(create_message(out2));
        d.insert_message(create_message(out));
        if (twice && !reverse)
            d.insert_message(create_message(out2));
    }
    State run;
    int n, got;
    bool keep, twice, reverse;
    DECLARE_INPUT_PORT(inp);
    DECLARE_OUTPUT_PORT(out);
    DECLARE_OUTPUT_PORT(out2);
};

// 받으면 그 시각에 한 번 낸다.
class Relay : public CAtomicModel
{
public:
    Relay(std::string name) : CAtomicModel(name), idle("IDLE", Infinity), send("SEND", 0), n(0)
    {
        REGISTER_INPUT_PORT(inp);
        REGISTER_OUTPUT_PORT(out);
        set_current_state(&idle);
    }
    void external_transition(Port&, Message&) override { set_current_state(&send); }
    void internal_transition() override { n++; set_current_state(&idle); }
    void output_function(MessageDeliverer& d) override
    {
        LOG.push_back(at(get_name().m_name));
        d.insert_message(create_message(out));
    }
    State idle, send;
    int n;
    DECLARE_INPUT_PORT(inp);
    DECLARE_OUTPUT_PORT(out);
};

// 시간 전진이 음수인 모델.
class Backward : public CAtomicModel
{
public:
    Backward(std::string name) : CAtomicModel(name) {}
    void external_transition(Port&, Message&) override {}
    void internal_transition() override {}
    void output_function(MessageDeliverer&) override {}
    Time time_advance() override { return -1; }
};

static CSystemExecutor* engine(Time step = 1)
{
    SimConfig c;
    c.engine_name = "facts";
    c.execution_mode = BLOCKING;
    c.simulation_mode = VIRTUAL;
    c.ef = new CExecutorFactory();
    c.time_resolution = step;
    LOG.clear();
    ENGINE = CSystemExecutor::create_system_executor(c);
    return ENGINE;
}

static std::string joined(const std::string& prefix = "")
{
    std::string out;
    for (const std::string& l : LOG)
        if (l.rfind(prefix, 0) == 0)
            out += (out.empty() ? "" : ",") + l;
    return out.empty() ? "-" : out;
}

int main()
{
    {   // 끝 시각: simulate(3)은 시각 3의 사건도 처리한다. 이어서 simulate(2)를 부르면 시각 6까지 간다
        auto* e = engine();
        auto* a = new Tick("a", 1);
        e->register_entity(a, 0, Infinity);
        e->simulate(3);
        std::cout << "horizon_first " << a->n << "\n";
        e->simulate(2);
        std::cout << "horizon_continued " << a->n << "\n";
    }
    {   // 끝 시각에 사건이 없어도 시계는 정확히 그 시각에 선다
        auto* e = engine();
        e->register_entity(new Tick("a", 1), 0, Infinity);
        Time back = e->simulate(2.5);
        std::cout << "clock_after_run " << (double)back << "," << (double)e->get_global_time() << "\n";
    }
    {   // 격자 밖의 시각: 주기 0.5, 시간 간격 1
        auto* e = engine();
        auto* a = new Tick("a", 0.5);
        auto* b = new Tick("b", 2);
        e->register_entity(a, 0, Infinity);
        e->register_entity(b, 0, Infinity);
        e->simulate(6);
        std::cout << "off_grid_half_period " << a->n << "\n";
        std::cout << "off_grid_other_model " << b->n << "\n";
    }
    {   // 다음 사건 시각이 같은 모델: c가 메시지를 받으면 c와 시각이 같은 d가 일정에서 빠진다
        auto* e = engine();
        auto* a = new Tick("a", 1);
        auto* c = new Tick("c", 5, true);
        auto* d = new Tick("d", 5);
        e->register_entity(a, 0, Infinity);
        e->register_entity(c, 0, Infinity);
        e->register_entity(d, 0, Infinity);
        e->insert_coupling(a, a->out, c, c->inp);
        e->simulate(12);
        std::cout << "equal_time_receiver " << c->n << "\n";
        std::cout << "equal_time_bystander " << d->n << "\n";
    }
    {   // 한 번의 출력에서 낸 메시지 둘
        auto* e = engine();
        auto* a = new Tick("a", 1, false, true);
        auto* b = new Tick("b", 100);
        auto* c = new Tick("c", 100);
        e->register_entity(a, 0, Infinity);
        e->register_entity(b, 0, Infinity);
        e->register_entity(c, 0, Infinity);
        e->insert_coupling(a, a->out, b, b->inp);
        e->insert_coupling(a, a->out2, c, c->inp);
        e->simulate(3);
        std::cout << "two_messages_first " << b->got << "\n";
        std::cout << "two_messages_second " << c->got << "\n";
    }
    {   // 같은 결합을 두 번 등록
        auto* e = engine();
        auto* a = new Tick("a", 1);
        auto* b = new Tick("b", 100);
        e->register_entity(a, 0, Infinity);
        e->register_entity(b, 0, Infinity);
        e->insert_coupling(a, a->out, b, b->inp);
        e->insert_coupling(a, a->out, b, b->inp);
        e->simulate(2);
        std::cout << "coupling_twice " << b->got << "\n";
    }
    for (int keep = 0; keep < 2; keep++)
    {   // 받는 쪽의 시계: 주기 3인 b가 매 시각 입력을 받는다
        auto* e = engine();
        auto* a = new Tick("a", 1);
        auto* b = new Tick("b", 3, keep);
        e->register_entity(a, 0, Infinity);
        e->register_entity(b, 0, Infinity);
        e->insert_coupling(a, a->out, b, b->inp);
        e->simulate(7);
        std::cout << (keep ? "receiver_timer_kept " : "receiver_timer ") << b->n << "\n";
    }
    {   // 같은 시각의 순서: 서로 잇지 않은 두 모델이 매 시각 함께 낸다
        auto* e = engine();
        e->register_entity(new Tick("a", 1), 0, Infinity);
        e->register_entity(new Tick("b", 1), 0, Infinity);
        e->simulate(4);
        std::cout << "simultaneous_order " << joined() << "\n";
    }
    {   // 같은 시각의 순서는 모델을 만든 순서다. 이름의 순서가 아니다
        auto* e = engine();
        e->register_entity(new Tick("b", 1), 0, Infinity);
        e->register_entity(new Tick("a", 1), 0, Infinity);
        e->simulate(2);
        std::cout << "creation_order " << joined() << "\n";
    }
    for (int last = 0; last < 2; last++)
    {   // 그 시각에 메시지를 받아 임박해진 모델의 차례: 나중에 만든 모델이면 이미 임박해 있던 모델보다 뒤에 온다
        auto* e = engine();
        Relay* r = last ? nullptr : new Relay("r");
        auto* a = new Tick("a", 1);
        auto* b = new Tick("b", 1);
        if (last)
            r = new Relay("r");
        e->register_entity(a, 0, Infinity);
        e->register_entity(b, 0, Infinity);
        e->register_entity(r, 0, Infinity);
        e->insert_coupling(a, a->out, r, r->inp);
        e->simulate(1);
        std::cout << (last ? "woken_model_made_last " : "woken_model_made_first ") << joined() << "\n";
    }
    for (int reverse = 0; reverse < 2; reverse++)
    {   // 한 번의 출력에서 낸 메시지들은 만든 순서로 전달된다
        auto* e = engine();
        auto* a = new Tick("a", 1, false, true, reverse);
        auto* b = new Tick("b", 100);
        auto* c = new Tick("c", 100);
        e->register_entity(a, 0, Infinity);
        e->register_entity(b, 0, Infinity);
        e->register_entity(c, 0, Infinity);
        e->insert_coupling(a, a->out, b, b->inp);
        e->insert_coupling(a, a->out2, c, c->inp);
        e->simulate(1);
        std::cout << (reverse ? "message_order_reversed " : "message_order ") << joined("ext-") << "\n";
    }
    {   // 자기 자신에게 이은 모델
        auto* e = engine();
        auto* s = new Tick("s", 2);
        e->register_entity(s, 0, Infinity);
        e->insert_coupling(s, s->out, s, s->inp);
        e->simulate(12);
        std::cout << "self_coupled " << s->n << "\n";
    }
    {   // 엔진의 경계로 나간 출력
        auto* e = engine();
        auto* a = new Tick("a", 1);
        e->register_entity(a, 0, Infinity);
        Port& x = e->create_output_port("x");
        Port& y = e->create_output_port("y");
        e->insert_coupling(a, a->out, e, x);
        e->insert_coupling(a, a->out, e, y);
        e->simulate(2);
        auto& out = e->get_external_output_deliverer().get_contents();
        std::string ports;
        for (auto& m : out)
            ports += (ports.empty() ? "" : ",") + m->get_source()->get_name().m_name + "." + m->get_out_port()->m_name;
        std::cout << "boundary_count " << out.size() << "\n";
        std::cout << "boundary_ports " << ports << "\n";
    }
    {   // 경계로 나간 출력을 받는 함수를 두면 엔진이 나가는 그때에 부른다
        auto* e = engine();
        auto* a = new Tick("a", 1);
        e->register_entity(a, 0, Infinity);
        Port& x = e->create_output_port("x");
        e->insert_coupling(a, a->out, e, x);
        std::string seen;
        e->set_output_handler([&](Message m) {
            std::ostringstream s;
            s << m->get_out_port()->m_name << "@" << (double)e->get_global_time();
            seen += (seen.empty() ? "" : ",") + s.str();
        });
        e->simulate(2);
        std::cout << "boundary_handler " << seen << "," << e->get_external_output_deliverer().get_contents().size() << "\n";
    }
    {   // 모든 모델이 쉬고 있을 때 예약된 외부 입력, 그리고 예약 시각이 같은 외부 입력 둘
        auto* e = engine();
        auto* r = new Tick("r", Infinity);
        e->register_entity(r, 0, Infinity);
        Port& in = e->create_input_port("x");
        e->insert_coupling(e, in, r, r->inp);
        e->insert_external_event(e->create_message(in, 3));
        e->simulate(6);
        std::cout << "external_input_passive " << joined("ext-") << "\n";
        e->insert_external_event(e->create_message(in, 9));
        e->insert_external_event(e->create_message(in, 9));
        e->simulate(5);
        std::cout << "external_input_same_time " << r->got - 1 << "\n";
    }
    for (int keep = 0; keep < 2; keep++)
    {   // 낼 시각과 같은 시각에 온 외부 입력: 입력이 먼저 전달된다. 다음 사건 시각을 지키지 않으면 그 시각의 출력이 밀린다
        auto* e = engine();
        auto* r = new Tick("r", 3, keep);
        e->register_entity(r, 0, Infinity);
        Port& in = e->create_input_port("x");
        e->insert_coupling(e, in, r, r->inp);
        e->insert_external_event(e->create_message(in, 3));
        e->simulate(5);
        std::cout << (keep ? "external_input_at_deadline_kept " : "external_input_at_deadline ") << joined() << "\n";
    }
    {   // 지금 시각의 외부 입력과 길이 0의 실행, 그리고 지난 시각의 외부 입력
        auto* e = engine();
        auto* r = new Tick("r", Infinity);
        e->register_entity(r, 0, Infinity);
        Port& in = e->create_input_port("x");
        e->insert_coupling(e, in, r, r->inp);
        e->simulate(2);
        e->insert_external_event(e->create_message(in, 2));
        e->simulate(0);
        std::cout << "external_input_now " << joined() << "\n";
        std::string what = "accepted";
        try
        {
            e->insert_external_event(e->create_message(in, 1));
        }
        catch (const std::invalid_argument&)
        {
            what = "invalid_argument";
        }
        std::cout << "external_input_past " << what << "\n";
    }
    {   // 외부 입력으로 그 시각에 임박해진 모델
        auto* e = engine();
        auto* r = new Relay("r");
        e->register_entity(r, 0, Infinity);
        Port& in = e->create_input_port("x");
        e->insert_coupling(e, in, r, r->inp);
        e->insert_external_event(e->create_message(in, 2));
        e->simulate(5);
        std::cout << "external_input_zero_delay " << joined() << "\n";
    }
    {   // 늦게 만들어지는 모델: 생성 시각 3, 주기 2
        auto* e = engine();
        e->register_entity(new Tick("a", 100), 0, Infinity);
        e->register_entity(new Tick("b", 2), 3, Infinity);
        e->simulate(9);
        std::cout << "late_creation " << joined("b") << "\n";
    }
    for (int nested = 0; nested < 2; nested++)
    {   // 같은 구조를 평탄하게 올린 것과 결합 모델 안에 넣은 것: 생성기 하나, 중계기 셋, 엔진의 출력
        auto* e = engine();
        auto* g = new Tick("g", 1);
        e->register_entity(g, 0, Infinity);
        Port& out = e->create_output_port("out");
        std::vector<Relay*> relays;
        std::string fired;
        if (nested)
        {
            auto* box = new CCoupledModel("box");
            Port& bi = box->create_input_port("bi");
            Port& bo = box->create_output_port("bo");
            for (int i = 0; i < 3; i++)
            {
                auto* r = new Relay("r" + std::to_string(i));
                relays.push_back(r);
                box->insert_model(r);
                box->insert_coupling(box, bi, r, r->inp);
                box->insert_coupling(r, r->out, box, bo);
            }
            e->register_entity(box, 0, Infinity);
            e->insert_coupling(g, g->out, box, bi);
            e->insert_coupling(box, bo, e, out);
        }
        else
        {
            for (int i = 0; i < 3; i++)
            {
                auto* r = new Relay("r" + std::to_string(i));
                relays.push_back(r);
                e->register_entity(r, 0, Infinity);
                e->insert_coupling(g, g->out, r, r->inp);
                e->insert_coupling(r, r->out, e, out);
            }
        }
        e->simulate(10);
        for (auto* r : relays)
            fired += (fired.empty() ? "" : ",") + std::to_string(r->n);
        std::cout << (nested ? "nested_boundary " : "flat_boundary ") << e->get_external_output_deliverer().get_contents().size() << "\n";
        std::cout << (nested ? "nested_relays " : "flat_relays ") << fired << "\n";
    }
    for (int started = 0; started < 2; started++)
    {   // 엔진을 지울 때 모델의 소멸자
        auto* e = engine();
        e->register_entity(new Tick("g", 1), 0, Infinity);
        if (started)
            e->simulate(3);
        DESTROYED = 0;
        delete e;
        std::cout << (started ? "destructor_after_run " : "destructor_never_run ") << DESTROYED << "\n";
    }
    std::cout << "virtual_destructor_model " << std::has_virtual_destructor<CModel>::value << "\n";
    {   // 시간 전진이 음수인 모델
        auto* e = engine();
        e->register_entity(new Backward("bad"), 0, Infinity);
        std::string what = "accepted";
        try
        {
            e->simulate(1);
        }
        catch (const std::domain_error&)
        {
            what = "domain_error";
        }
        std::cout << "negative_time_advance " << what << "\n";
    }
    {   // 값을 싣는 포트와 값 없는 포트를 잇기
        auto* e = engine();
        auto* a = new Tick("a", 1);
        auto* b = new Tick("b", 1);
        e->register_entity(a, 0, Infinity);
        e->register_entity(b, 0, Infinity);
        ValuePort<int> typed("typed");
        std::string what = "accepted";
        try
        {
            e->insert_coupling(a, typed, b, b->inp);
        }
        catch (const std::invalid_argument&)
        {
            what = "invalid_argument";
        }
        std::cout << "value_port_to_plain_port " << what << "\n";
    }
    return 0;
}
