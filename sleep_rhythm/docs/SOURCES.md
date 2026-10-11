# 확인한 출처

확인일: 2026-10-10(v2.0), 2026-10-11(v2.1 추가 항목). 각 항목에 “앱에서 쓴 곳”과 “쓰지 않은 것”을 함께 적었다. 아래 연구는 모형의 개념적 출발점이며, 이 앱의 매개변수나 예측 성능을 검증한 자료가 아니다.

## 연구

1. Hong, J., Choi, S. J., Park, S. H., Hong, H., Booth, V., Joo, E. Y., & Kim, J. K. (2021). Personalized sleep-wake patterns aligned with circadian rhythm relieve daytime sleepiness. *iScience*, 24(10), 103129. https://doi.org/10.1016/j.isci.2021.103129 (공개 원문: https://pmc.ncbi.nlm.nih.gov/articles/PMC8479255/)
   - 확인 범위: PMC 공개 원문의 서지, 초록, circadian necessary sleep과 CSS의 정의, CSS와 낮 졸림의 관계를 서술한 문장.
   - 원문 정의: circadian necessary sleep은 “the sleep episode with the minimum duration required so that awakening occurs in the potential wake region”, CSS는 “the fraction of circadian sufficient sleeps in total sleep days during the study period”.
   - 원문 결과(서술): 초록 “shift workers who align sleep-wake patterns with their circadian rhythm have lower daytime sleepiness, even if they sleep less”, 본문 “CSS was significantly correlated with daytime sleepiness”(Epworth 졸림 척도).
   - 앱에서 쓴 곳: “필요 수면 종료” = 잠든 뒤 S ≤ C인 마지막 구간의 시작이라는 단순화된 정의, 계획서 §8의 역계산, 분석 탭의 “필요 수면을 채운 날의 비율”(CSS 개념을 단순화한 앱 계산, 15분 허용) 해설과 “일주기에 맞춰 충분히 잔 날의 비율이 높을수록 낮 졸림이 낮았다”는 연구 소개 문장.
   - 쓰지 않은 것: 원논문의 생리학적 모형·매개변수·CSS 계산 코드, 상관계수 등 결과 수치. 앱의 비율은 원논문의 CSS 값이 아니며 그 결과를 이 앱 사용자에게 옮기지 않는다.

2. Song, Y. M., Choi, S. J., Park, S. H., Lee, S. J., Joo, E. Y., & Kim, J. K. (2023). A real-time, personalized sleep intervention using mathematical modeling and wearable devices. *SLEEP*, 46(9), zsad179. https://doi.org/10.1093/sleep/zsad179 (출판사: https://academic.oup.com/sleep/article/46/9/zsad179/7221723)
   - 확인 범위: 출판사 페이지의 서지와 방법 일부.
   - 원문 내용: 예측 각성도는 일주기 수면 임계값에서 항상성 수면압을 빼서 계산하며, 각 개인의 처음 4일 예측은 신뢰도가 낮아 제외했다.
   - 앱에서 쓴 곳: AL = C − S, 처음 4일 준비 기간(5일째부터 추천).
   - 쓰지 않은 것: 웨어러블 자료, 원 모형, ACSS(분할 수면) 알고리즘, 연구 대상(교대근무 간호사)의 결과를 다른 사람에게 옮기는 해석.

3. Skeldon, A. C., Dijk, D.-J., & Derks, G. (2014). Mathematical models for sleep-wake dynamics: Comparison of the two-process model and a mutual inhibition neuronal model. *PLOS ONE*, 9(8), e103877. https://doi.org/10.1371/journal.pone.0103877 (arXiv:1311.1734)
   - 확인 범위: arXiv 원문 Figure 1 설명의 매개변수 “χs = 4.2 hrs, χw = 18.2 hrs”.
   - 앱에서 쓴 곳: 수면압 시간상수 τw = 18.2시간, τs = 4.2시간.

## 연령별 수면량

4. Centers for Disease Control and Prevention. *About Sleep*. 마지막 검토 2023-11-20, 마지막 수정 2024-05-15. https://www.cdc.gov/sleep/about/index.html
   - 확인 범위: 연령별 하루 권장 수면시간 표(0–3개월 14–17시간, 4–12개월 12–16시간, 1–2세 11–14시간, 3–5세 10–13시간(4개월~5세는 낮잠 포함), 6–12세 9–12시간, 13–17세 8–10시간, 18–60세 7시간 이상, 61–64세 7–9시간, 65세 이상 7–8시간).
   - 앱에서 쓴 곳: 연령별 최소 수면시간(반드시 지킬 조건)과 권장 상한. 성인 9시간 탐색 상한, 추천 제공 연령, 낮잠을 최소 수면에 넣지 않는 규칙은 앱 설계다.

   - v2.1 추가 확인: 같은 페이지 “What to do”의 생활 습관(Going to bed and getting up at the same time every day 등 6개). 분석 탭의 “잠을 돕는 생활 습관 (CDC)”에 옮겼고, 규칙성 해설의 “CDC는 매일 같은 시각에 자고 일어나기를 권해요” 문장에 썼다.

5. American Academy of Sleep Medicine. (2014, August 11). *Get the kids to sleep and ready for back to school*. https://aasm.org/get-the-kids-to-sleep-and-ready-for-back-to-school/
   - 확인 범위: “easing bedtime back at least 15 minutes earlier each night, then waking the kids up 15 minutes earlier in the morning”.
   - 앱에서 쓴 곳: 취침을 크게 앞당길 때의 안내 문구. 학생 개학 대비 안내이며 성인 연구 근거가 아니다.

## 분석 탭에 추가한 출처 (v2.1)

6. Wittmann, M., Dinich, J., Merrow, M., & Roenneberg, T. (2006). Social jetlag: misalignment of biological and social time. *Chronobiology International*, 23(1–2), 497–509. https://doi.org/10.1080/07420520500545979 (PubMed 16687322)
   - 확인 범위: PubMed 초록 “The discrepancy between work and free days, between social and biological time, can be described as ‘social jetlag.’”
   - 앱에서 쓴 곳: 평일·주말 수면 중간 시각 차이 해설에서 ‘사회적 시차’라는 용어 소개. 차이 계산(토·일 아침 기상일과 평일의 수면 중간 시각 차이)과 1·2시간 표시 기준은 앱의 단순 계산이며 원논문의 측정 방법(설문)이나 기준이 아니다.

7. Åkerstedt, T., & Gillberg, M. (1990). Subjective and objective sleepiness in the active individual. *International Journal of Neuroscience*, 52, 29–37.
   - 확인 범위: 카롤린스카 졸림 척도(KSS) 1~9단계 중 기준점 1 “extremely alert”, 3 “alert”, 5 “neither alert nor sleepy”, 7 “sleepy – but no difficulty remaining awake”, 9 “extremely sleepy – fighting sleep”(펜실베이니아대 CBT-I 자료의 KSS 장, Wikipedia 표와 대조).
   - 앱에서 쓴 곳: 깬 직후·수업 중 졸림 버튼 1·3·5·7·9의 이름(매우 또렷·또렷·보통·졸림·매우 졸림). 저장 값은 v2.0과 같은 1~9 정수다.

## 배포

8. Pylons Project. *Waitress 3.0.2 documentation — Arguments*. https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html
   - 생산용 WSGI 서버 설정(threads, max_request_body_size, channel_timeout 등)과 기본값 확인. 3.0부터 신뢰하지 않는 프록시 헤더를 기본으로 제거한다.

9. Render 문서 (확인일 2026-10-10)
   - Blueprint 명세(render.yaml): https://render.com/docs/blueprint-spec — `type: web`, `runtime: python`, `plan: free`, `buildCommand`, `startCommand`, `healthCheckPath`, `autoDeployTrigger`, `region`(singapore 포함).
   - Python 버전: https://render.com/docs/python-version — 새 서비스 기본 3.14.3, `.python-version` 파일은 `3.13`처럼 패치 버전을 생략할 수 있고 `PYTHON_VERSION` 환경 변수가 우선한다.
   - 무료 인스턴스: https://render.com/docs/free — 15분 동안 요청이 없으면 잠들고 다시 깨는 데 약 1분, 월 750시간, 사용자 지정 도메인과 관리형 TLS 지원, 운영 서비스 용도로는 권장하지 않음.
   - 실제 계정으로 배포하지는 않았다.

## 쓰지 않은 내용

계획서에 적힌 원연구의 세부 수치(참여자 수, 상관계수, p값, 매개변수 개수 등)는 앱의 화면과 계산에 쓰지 않았다. 청소년의 수면압 시간상수 같은 연령별 값은 원문을 확인하지 못해 넣지 않았다. 원논문의 코드·그림·긴 문장을 패키지에 복제하지 않았고, 수면압·주기 함수의 구현과 화면은 새로 작성했다.
