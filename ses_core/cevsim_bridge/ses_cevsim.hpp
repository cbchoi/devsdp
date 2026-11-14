// cevsim 모델을 SES 실행기의 모듈로 등록하는 자리 (docs/ses-platform/16_cevsim_executor.md).
//
// cevsim의 원자 모델(evsim::CAtomicModel)을 만드는 공장을 모듈 이름으로 등록한다. 실행기는
// 계획의 원자마다 그 모듈의 공장을 불러 모델을 만들고 엔진에 올린다. 매개변수는 글자로 온다.
//
//     SES_MODULE(Source, [](const std::string& name, const ses::Params& p) {
//         return new CSource(name, p.time("period", 1));
//     });
//
// 공장은 부를 때마다 new로 만든 새 모델을 돌려준다. 그 모델은 실행기와 엔진이 넘겨받아 지운다.
// 이 파일과 모델의 소스는 실행기가 cevsim과 함께 하나의 공유 라이브러리로 컴파일한다.
#pragma once

#include <functional>
#include <map>
#include <string>

#include "atomic_model.hpp"

namespace ses {

struct Params {
    std::map<std::string, std::string> values;

    bool has(const std::string& key) const { return values.count(key) > 0; }
    std::string text(const std::string& key, const std::string& fallback = "") const;
    long double number(const std::string& key, long double fallback = 0) const;
    evsim::Time time(const std::string& key, evsim::Time fallback = evsim::Infinity) const;    // inf는 evsim::Infinity가 된다
};

typedef std::function<evsim::CAtomicModel*(const std::string& name, const Params& params)> Factory;

bool add_module(const std::string& module, Factory factory);

}   // namespace ses

#define SES_MODULE(MODULE, FACTORY) static const bool ses_module_##MODULE = ses::add_module(#MODULE, FACTORY)
