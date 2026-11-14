// cevsim 실행기의 시험에 쓰는 고유 모델들 (tests/test_cevsim.py).
// cevsim의 원자 모델을 만드는 공장을 SES_MODULE로 등록한다.
#include <cstdint>
#include <stdexcept>
#include <string>

#include "atomic_model.hpp"
#include "ses_cevsim.hpp"
#include "value_message.hpp"

using namespace evsim;

// 주기마다 out으로 낸다. twice이면 out2로도 낸다. keep이면 입력을 받아도 다음 사건 시각을 지킨다.
class CTick : public CAtomicModel
{
public:
    CTick(std::string name, Time period, bool keep, bool twice)
        : CAtomicModel(name), run("RUN", period), keep(keep), twice(twice)
    {
        REGISTER_INPUT_PORT(inp);
        REGISTER_OUTPUT_PORT(out);
        REGISTER_OUTPUT_PORT(out2);
        set_current_state(&run);
    }

    void external_transition(Port&, Message&) override
    {
        if (keep)
            set_cancel_reschedule(true);
    }

    void internal_transition() override {}

    void output_function(MessageDeliverer& deliverer) override
    {
        deliverer.insert_message(create_message(out));
        if (twice)
            deliverer.insert_message(create_message(out2));
    }

    State run;
    bool keep, twice;
    DECLARE_INPUT_PORT(inp);
    DECLARE_OUTPUT_PORT(out);
    DECLARE_OUTPUT_PORT(out2);
};

// 받으면 그 시각에 한 번 낸다.
class CRelay : public CAtomicModel
{
public:
    CRelay(std::string name) : CAtomicModel(name), idle("IDLE", Infinity), send("SEND", 0)
    {
        REGISTER_INPUT_PORT(inp);
        REGISTER_OUTPUT_PORT(out);
        set_current_state(&idle);
    }

    void external_transition(Port&, Message&) override { set_current_state(&send); }
    void internal_transition() override { set_current_state(&idle); }
    void output_function(MessageDeliverer& deliverer) override { deliverer.insert_message(create_message(out)); }

    State idle, send;
    DECLARE_INPUT_PORT(inp);
    DECLARE_OUTPUT_PORT(out);
};

SES_MODULE(Tick, [](const std::string& name, const ses::Params& p) -> CAtomicModel* {
    return new CTick(name, p.time("period", 1), p.number("keep") != 0, p.number("twice") != 0);
});

SES_MODULE(Relay, [](const std::string& name, const ses::Params&) -> CAtomicModel* { return new CRelay(name); });

SES_MODULE(Nothing, [](const std::string&, const ses::Params&) -> CAtomicModel* { return nullptr; });

// 주기마다 지금까지 낸 횟수를 값 메시지로 낸다.
class CCount : public CAtomicModel
{
public:
    CCount(std::string name, Time period) : CAtomicModel(name), run("RUN", period), n(0)
    {
        register_output_port(out);
        set_current_state(&run);
    }

    void external_transition(Port&, Message&) override {}
    void internal_transition() override { n++; }
    void output_function(MessageDeliverer& deliverer) override { deliverer.insert_value(this, out, n); }

    State run;
    std::uint64_t n;
    ValuePort<std::uint64_t> out{"out"};
};

// 값 메시지를 받아 그 수가 짝수이면 그 시각에 한 번 낸다.
class CEven : public CAtomicModel
{
public:
    CEven(std::string name) : CAtomicModel(name), idle("IDLE", Infinity), send("SEND", 0)
    {
        register_input_port(inp);
        REGISTER_OUTPUT_PORT(out);
        set_current_state(&idle);
    }

    void external_transition(Port&, Message&) override {}
    void external_value_transition(Port&, const ValueMessage& message) override
    {
        if (message.as<std::uint64_t>().value() % 2 == 0)
            set_current_state(&send);
    }
    void internal_transition() override { set_current_state(&idle); }
    void output_function(MessageDeliverer& deliverer) override { deliverer.insert_message(create_message(out)); }

    State idle, send;
    ValuePort<std::uint64_t> inp{"inp"};
    DECLARE_OUTPUT_PORT(out);
};

SES_MODULE(Count, [](const std::string& name, const ses::Params& p) -> CAtomicModel* {
    return new CCount(name, p.time("period", 1));
});

SES_MODULE(Even, [](const std::string& name, const ses::Params&) -> CAtomicModel* { return new CEven(name); });

// 규칙을 어기는 공장: again이면 앞서 내놓은 모델을 다시 내놓는다.
static CAtomicModel* previous = nullptr;

SES_MODULE(Again, [](const std::string& name, const ses::Params& p) -> CAtomicModel* {
    if (p.number("again") != 0)
        return previous;
    return previous = new CRelay(name);
});

// 정해진 시각에 내려다가 예외를 던진다.
class CThrower : public CAtomicModel
{
public:
    CThrower(std::string name, Time at) : CAtomicModel(name), run("RUN", at) { set_current_state(&run); }

    void external_transition(Port&, Message&) override {}
    void internal_transition() override {}
    void output_function(MessageDeliverer&) override { throw std::runtime_error("thrower"); }

    State run;
};

SES_MODULE(Thrower, [](const std::string& name, const ses::Params& p) -> CAtomicModel* {
    return new CThrower(name, p.time("at", 1));
});
