# Tests do not build or pass with g++ 13.3 on Linux x86-64 (cevsim 45e7fa9)

## Summary

| Item | Value |
|---|---|
| Commit | 45e7fa9 (main) |
| Toolchain | g++ 13.3.0 (Ubuntu 24.04), Linux x86-64, CMake 3.28.3, Release build with BUILD_TESTING=ON |
| GoogleTest | 1.14.0 from the Ubuntu source package. The pinned revision could not be downloaded in that environment |
| Library | builds without errors |
| CTest entries | 24 registered. 16 pass, 5 are not run because 6 targets do not compile, 3 fail |
| Failing GoogleTest cases | 11, in the 3 failing entries |

docs/PUBLICATION_20261114.md and docs/validation-20261114.json record 24 of 24 entries with MSVC (Microsoft Visual C++) 19.51. README.md asks only for "a compiler supporting C++23".

Every failure is in test code. None of them is evidence of a defect in the engine. There are three causes. Three alternative changes were tried on a copy of the commit, and with each of them all 24 entries pass on the same toolchain. The smallest one touches test sources only (7 files, 17 lines, attached as cevsim_45e7fa9_gxx_linux_tests.patch).

## Causes

### 1. A dependent template name without the `template` keyword

tests/include/debugging_fixture.hpp:122

```cpp
retained_reply = packet.as<Reply>().retain();
```

`packet` is declared `const auto` from a call that takes `this` inside the class template `DelayedResponseModel<FaultyCancellation>`. Its type is dependent, so the member template needs the keyword. The project sets CMAKE_COMPILE_WARNING_AS_ERROR, and g++ stops with

```
debugging_fixture.hpp:122:33: error: expected 'template' keyword before dependent template name [-Werror=missing-template-keyword]
```

Affected: cevsim_debugging_tests, cevsim_debugging_demo, cevsim_debugging_localization_demo and cevsim_debugging_candidate_demo do not compile. The CTest entry cevsim_debugging_tests is not run.

Change: `packet.template as<Reply>().retain();`. cevsim/include/value_message.hpp:143 already writes `m_message->template read<T>()` in the same situation.

### 2. `Time` is `long double`, and its size differs between platforms

cevsim/include/definition.hpp:36 has `typedef long double Time;`. With MSVC on x64 a long double has 8 bytes and the precision of double. With g++ on Linux x86-64 it is the 80-bit extended format: 16 bytes, 16-byte alignment and a 64-bit mantissa. Two groups of tests depend on the MSVC size.

2a. Value payloads larger than 32 bytes

| File | Struct |
|---|---|
| benchmarks/repair/structural_effects_20261114/tests/effect_tests.cpp:36 | `Packet` with four uint32, one uint64 and one Time |
| benchmarks/repair/component_reuse_20261114/tests/component_tests.cpp:49 | `Packet` with one int32, two int16, two int64 and one Time |

Both hold 24 bytes of other data and one Time. That is 32 bytes with MSVC and 48 bytes here, above `value_payload_capacity` (cevsim/include/value_message.hpp:22).

```
value_message.hpp:56:29: error: static assertion failed: Value payload exceeds 32 inline bytes
value_message.hpp:56:29: note: the comparison reduces to '(48 <= 32)'
```

Affected: cevsim_structural_effect_tests and cevsim_component_reuse_tests do not compile. Four CTest entries are not run, because each program is registered twice, the second time with --fresh.

2b. The end time of `simulate(2)` compared with the double literal 2.1

The clock stands at the double value 0.1, and `simulate(2)` returns 0.1 plus 2 computed in Time. In the 80-bit format that sum is exact, 2.1000000000000000055. The double literal 2.1 is 2.1000000000000000888. With MSVC the sum is rounded to double precision, which gives the double 2.1, and the comparison holds.

| Site | Failing case |
|---|---|
| tests/include/test_checkpoint_restore_fast.hpp:146 | CheckpointRestoreFast.DecodeFailureAfterLoadedAliasesRollsBackAndCanContinueExactly |
| tests/include/test_checkpoint_restore_body.hpp:162 | CheckpointRestoreBody.LateDecodeFailureResetsSharedTablesAndRollsBackExactContinuation |
| tests/checkpoint_layout_tests.cpp:124 | CheckpointRestoreLayout.LateDecodeFailureRollsBackMutableBodyAndMessageAliases |
| tests/checkpoint_numeric_tests.cpp:190 | CheckpointRestoreNumeric.LateDecodeFailureRollsBackMutableBodyAndMessageAliases |
| tests/checkpoint_numeric_tests.cpp:397 | CheckpointRestoreNumeric.NumericOnlyEnvelopeAndBodyRollbackPreserveContinuation |

The first two sites are in headers that three test programs include, so each of them fails three times. That gives 9 failing case instances: 2 in cevsim_checkpoint_tests, 3 in cevsim_checkpoint_layout_tests and 4 in cevsim_checkpoint_numeric_tests. Every site has the same comparison for `oracle` next to the one for `target`.

Change used here: compare with `Time(0.1) + 2` in both comparisons of each site.

### 3. A string limit that relies on the length of `typeid` names

tests/checkpoint_layout_tests.cpp:32 and tests/checkpoint_numeric_tests.cpp:32

```cpp
limited = refs; limited.limits.max_string_bytes = 1;
checkpoint::Reader string(writer.buffer(), limited);
EXPECT_THROW(string.matches_immutable_fields(std::uint32_t{1}), checkpoint::ArchiveError);
```

`matches_immutable_fields` reads the stored type tag first, and the tag is `typeid(T).name()` (cevsim/include/checkpoint_archive.hpp:266 and 357). The tag is the only string this call reads. With MSVC the tag of std::uint32_t is "unsigned int", 12 bytes, and the limit of 1 is exceeded. With g++ it is "j", 1 byte. The limit holds and nothing is thrown.

```
Expected: string.matches_immutable_fields(std::uint32_t{1}) throws an exception of type checkpoint::ArchiveError.
  Actual: it throws nothing.
```

Affected: CheckpointRestoreLayout.ImmutableComparisonUsesTheNormalCodecAndLimits and CheckpointRestoreNumeric.ImmutableComparisonUsesTheNormalCodecAndLimits, 2 failing cases.

Change used here: a limit of 0. tests/checkpoint_numeric_tests.cpp:91 already uses a portable form, `tag_size-1`, for a similar check.

## What was tried

Each variant was applied to a copy of 45e7fa9 and built with the toolchain above.

| Variant | Change | Result |
|---|---|---|
| A. Test code only | changes for causes 1, 2b and 3. For 2a the two `Packet` structs store the time as double, with three casts in effect_tests.cpp | 24 of 24 entries pass |
| B. Time as double | changes for causes 1 and 3. In cevsim/include/definition.hpp:36 `typedef double Time;` and the matching `Infinity` on the next line | 24 of 24 pass. The `Packet` structs and the 2.1 comparisons are untouched |
| C. Larger payload capacity | changes for causes 1, 2b and 3. In cevsim/include/value_message.hpp:22 `value_payload_capacity = sizeof(Time) > 8 ? 48 : 32` | 24 of 24 pass. The `Packet` structs are untouched |

Variant A is the attached patch. It applies to 45e7fa9 with `git apply`.

Notes:

- In variant A, 634 GoogleTest cases are listed in 18 programs. The record for MSVC says 641. tests/include/test_affinity.hpp compiles some cases only on Windows, and one case is skipped by design on other systems (Affinity.WindowsWorkerAffinityRequiresWindows).
- Variant A changes two files under benchmarks/. The file .gitattributes marks everything under that folder as material whose bytes are preserved. If those files must stay as they are, B or C solves 2a without touching them.
- Variant B gives every platform the same time arithmetic. With MSVC the representation stays the same but the type changes, and with it the type tag written into checkpoints.
- Variant C makes the payload capacity depend on the platform.
- None of the variants was built with MSVC or Clang.

## Related observation: results depend on the width of long double

This is not a test problem. It has the same root as cause 2 and it affects reproducibility across platforms. A model with period 0.1 and a model with period 1.0 were run with the program below.

| long double | `simulate(1.0)`: outputs of the 0.1 model | `simulate(1.05)`: order of the tenth 0.1 output and the 1.0 output |
|---|---|---|
| 80-bit format (g++ on Linux x86-64) | 9 | the 1.0 model first |
| double precision (g++ with -mlong-double-64, the width MSVC uses) | 10 | the 0.1 model first |

Ten additions of the double 0.1 give 0.9999999999999999 in double precision, which is before 1.0. In the 80-bit format they give 1.0000000000000000555, which is after 1.0. The same source therefore produces a different number of events and a different order of events. The second row was measured with the g++ option, not with MSVC.

```cpp
#include <cstdio>
#include <string>
#include <vector>

#include "atomic_model.hpp"
#include "executor_factory.hpp"
#include "sim_config.hpp"
#include "system_executor.hpp"

using namespace evsim;

static std::vector<std::string> order;

class Periodic : public CAtomicModel
{
public:
    Periodic(std::string name, Time period) : CAtomicModel(name), run("RUN", period), fired(0) { set_current_state(&run); }
    void external_transition(Port&, Message&) override {}
    void internal_transition() override { ++fired; }
    void output_function(MessageDeliverer&) override { order.push_back(get_name().m_name); }
    State run;
    int fired;
};

int main()
{
    SimConfig c;
    c.engine_name = "period";
    c.execution_mode = BLOCKING;
    c.simulation_mode = VIRTUAL;
    c.ef = new CExecutorFactory();
    c.time_resolution = 1;
    CSystemExecutor* engine = CSystemExecutor::create_system_executor(c);
    auto* fast = new Periodic("fast", 0.1);
    auto* whole = new Periodic("whole", 1.0);
    engine->register_entity(fast, 0, Infinity);
    engine->register_entity(whole, 0, Infinity);
    engine->simulate(1.0);                      // 1.05 for the second column
    std::printf("fast fired %d times, whole fired %d times\n", fast->fired, whole->fired);
    for (const auto& name : order)
        std::printf(" %s", name.c_str());
    std::printf("\n");
}
```

## Minor: warnings in public headers

A client that includes the public headers and compiles with -Wall -Wextra gets five warnings from g++. With -Werror in the client they stop its build. The library's own build does not enable these warnings.

| Header | Warning |
|---|---|
| cevsim/include/checkpoint_archive.hpp:521, 526, 531 and 541 | -Wmisleading-indentation. A `return` follows an `if (...) throw ...;` on the same line. The code is correct |
| cevsim/include/system_executor.hpp:166 | -Wunused-parameter for `global_time` |

## Not verified

- MSVC and Clang with any of the changes.
- The optional benchmark targets (CEVSIM_BUILD_BENCHMARKS).
- GoogleTest at the pinned revision. Version 1.14.0 from the distribution was used.
