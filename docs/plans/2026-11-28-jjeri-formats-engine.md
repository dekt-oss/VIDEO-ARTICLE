# 째리 모션그래픽 두 형식 구현 계획

기준은 origin/main `eaafa47`의 술 해부 핸드오프 §7과 술 수업 핸드오프 11-28 정정이다. 현재 작업 공간에는 검증된 술 수업과 웹 지시서 생성 변경이 미커밋 상태로 있다. 새 기준을 적용하되 기존 작업은 보존한다. 리포트 `engine/motion`의 기존 실행 경로와 밈 제작 계약을 유지한다.

1. **M0 계획과 검토.** Codex가 두 명세, 최신 `engine/hf_render.py`, 기존 클래스·제작 연결을 대조한다. 검토 후 최신 main과 기존 변경을 별도 로컬 작업 공간에서 합친다. 겹치는 파일은 두 버전의 기능을 보존하고 라이브 배포 작업과 분리한다.
2. **M1 정답 재현.** `hf_templates/jjeri-anatomy/`부터 시작해 네 세계, 회전체 부품, 카메라, 토큰, HUD와 퀴즈를 지시서 변수로 조립한다. 등록된 사건만 디스패치하고 `beat/at/from_end`를 검증한다. 다음으로 기존 술 수업의 12종 장면·자막·시간표·검사 로직을 `hf_templates/jjeri-class/`로 연결한다. 두 형식이 `engine/hf_render.py`의 고정 CLI·환경 필터·길이 검증·원자적 출력·음량 정규화 경로를 공유한다. 로컬 GSAP·글꼴과 저장 음성으로 비교하며, 골든과 달라지는 박자 이동은 M1.5의 별도 출력에만 적용한다. 원본 샘플들을 별도 시험 자료로 유지한다.
3. **M1.5 자체 곡.** ledger의 소유 곡 하나만 읽는다. 117 BPM, 첫 박 0.3598초, 네 박 한 마디 약 2.051282초를 사용한다. 원본 파일에서 마디별 파형·트랜지언트를 측정하고 상승음·클릭·로고로 들리는 시각과 피할 구간을 기록한다. 깨끗한 연속 마디를 고르고 절단·연결 후 박자 검출로 실제 위상과 접합부를 확인한다. 최종 완전 마디 경계 직전 1초를 페이드하고 남는 영상 꼬리는 음성·효과음과 영상을 그대로 유지한다. 내레이션·세계 호스트 시작을 고정하고 세계 전환 연출, 의성어·칩·도장 등 지정 악센트만 ±0.12초 안에서 이동한다. 경계 밖, 자막을 가리거나 선후관계를 깨는 후보는 이동하지 않고 이유를 기록한다. HUD는 0.5128205초 간격이며 첫 단계와 후속 단계의 실제 프레임 및 효과음 시작을 확인한다. 배경음 0.16, 최종 −14 LUFS 목표로 렌더한다.
4. **M2 지시서 검사.** 세계·부품·토큰·동사와 칸의 허용 목록, 유일한 ID, 참조, 시간 범위, 자막 2줄/17자, 가격 금지, 앞에서 나온 내용만 퀴즈 정답 허용, 마지막 퀴즈와 `loop_return`을 검사한다. 샘플의 기확인 초과 자막·빈 claim은 정답 비교 전용 경로에만 둔다. 신규 입력으로 그 경로를 선택할 수 없다. 금지 입력과 각 동사의 정상 입력을 실제 렌더 앞에서 시험한다.
5. **M3 근거 대본.** 두 형식 모두 승인 근거 자료와 허용 목록을 응답 공급자에게 전달하고 `drinks_script_check` 차단, 화면 값·문장별 claim·출처 일치, 퀴즈 앞 문장 일치를 적용한다. 모의 최초 응답과 교정 응답, 근거 철회, 승인 없는 제작 차단을 0원으로 리허설한다. 실제 모델 호출은 별도 명시적 승인 대상이다.
6. **M4 새 세계.** 같은 단면·광원·카메라 계약으로 숙성 통 등 새 세계 한 종류를 등록한다. 테스트는 구조와 렌더로 확인하고 실제 편의 원문 일치와 디자인은 소유자 판정을 받는다.
7. **M5 제작 큐와 화면.** 기존 주류 작업의 권한·비용·임대·승인 해시·QA·게시 차단을 두 형식에 연결한다. 기능별로 요청, 렌더, 파일 등록, 취소, 근거 철회, 이전 워커 호환을 로컬 DB에서 확인한다. 웹에서 두 선택지·미리보기·실패 사유를 검증한다. 마이그레이션 번호는 실제 운영 등록부 대조 후 부여한다.

### 합격 증거와 적용

- M1은 세계·문장 및 술 수업 장면 시작 오차 각각 ±0.05초 안, 해부 14장·수업 12장 동일 시각 프레임 비교표, 안전 영역 검사 오류 0으로 판정한다. 입력에서 토큰·문장·카메라 시점을 바꿨을 때 출력도 바뀌는지 확인한다. `check`와 `render`는 각각 실행한다.
- M1.5는 두 곡 적용 MP4를 `renders/`에 보관한다. 각 사건의 이전·이후 시간, 실제 오디오 박, 비디오 프레임, 오차를 표로 남긴다. 이동한 사건은 33ms 내 일치와 0.12초 이동 상한을 모두 검사하고 TTS와 화면 타임라인이 변경되지 않았음을 확인한다. 음원 마디와 피해야 할 효과음의 실측은 계획서에 추가한다.
- TTS는 현수 +10%와 atempo 1.055를 사용한다. 빈 음성·렌더 시간 초과는 잡 실패로 기록한다. 그림·영상 생성 API는 사용하지 않는다.
- 공용 하네스의 전체 pytest와 smoke, 현행 밈 및 리포트 회귀를 기록한다. 코드 리뷰와 독립 Fable 검사 후 단계별 PR에 결과를 붙인다. 원격 SQL 적용·크론·게시·유료 호출은 별도 승인 전 대기한다.
- 되돌릴 때 새 요청을 끄고 대기 작업을 취소·확인한 뒤 이전 워커로 전환한다. 기존 자산과 작업 이력은 보존한다.

### Codex 계획 리뷰 수정 사항

초기 판정은 P1 다섯 건 수정 필요였다. 아래 계약을 구현 및 합격 판정에 적용한다.

1. **데이터에서 실제 출력까지.** 편마다 바뀌는 문장, 세계·부품·층·토큰·이름표, 퀴즈 질문·보기·정답, 사건과 소리 트리거는 지시서 및 검증된 등록 기본값에서 해석한다. 고정 좌표·광원·효과음 라이브러리는 템플릿 책임이다. 세계 시간 원점, 문장 원점, 끝 원점은 서로 다른 표현으로 처리한다. 예제의 퀴즈 지시서 `beat+0.3`은 39.47초지만 골든 시각은 39.32초다. 이 차이와 누락된 입력을 원본 빌더·시간표와 대조해 호환 처리 또는 지시서 정정으로 명시하고 테스트한다. 장면 ID나 제목으로 결과를 고르는 분기는 불합격이다. 입력 → 검증 → 합성 프로젝트 → `hf_render` 공용 실행 → 출력으로 가고, 밈 전용 API와 리포트는 기존 계약을 유지한다. 샘플 음성 매니페스트는 음성 파일 SHA와 실제 발화 문장을 묶고, 자막만 바꾼 구조 검증은 음성 재현 근거에서 분리한다.
2. **골든과 자체 곡의 모드.** M1의 해부 HUD 0.35초 간격은 원본을 유지한다. M1.5에서 첫 HUD 단계는 원시 사건에 대해 ±0.12초 내 박 정렬을 시도하고, 이후 단계들은 명시된 연출 변경으로 0.5128205초마다 배치한다. 끝의 완료 시각은 원문·세계 경계를 넘기지 않는다. 첫 단계 8.229초가 박 8.0521초에서 177ms 떨어지는 예에서는 위상이 동일하다면 옮기지 않는다. 그때 후속 단계의 박 오차도 표시하며 정렬됐다고 주장하지 않는다. 자막·음성·호스트 시작은 고정한다. 박에 맞추는 시각과 연결된 SFX의 기준점은 함께 옮기고, MP4 첫 표시 PTS와 실제 SFX 피크 또는 onset, 실제 오디오 박을 각각 비교한다. ±0.12초는 개별 악센트 이동 한도이고 HUD 후속 단계의 의도된 재배치는 별도 기록한다. 실제 박과 정렬됐다는 판정은 최종 결과에서 1/30초 안일 때만 부여한다.
3. **마디 접합 실측.** Codex가 원본 WAV와 ledger AAC의 해시를 확인했다. AAC 실측 24.047초, 상승음 소스 2.400–2.800초는 AAC 절단 전, AAC 클릭 후보 5.325초, 로고 고역 피크 19.853초, 킥 약화 2.547–7.547초와 박 공백 7.539–9.077초다. 반복 후보는 AAC 10.103410–18.308538초(원곡 k20→36, 네 마디)다. 이 구간의 저역 상승 피크는 기준 박보다 +1~25ms이며 하드컷 경계 샘플 차는 0.0363이다. 효과음 구분은 소스 표식·신호 기준이며 청감 및 접합 합격은 미검증이다. ledger 첫 박은 원곡의 k1로 보고 k%4=0을 마디 경계로 잡는다. PCM 표본 단위로 절단하고 짧은 접합 처리 뒤 실제 결과의 위상·재생 길이와 시작/끝 프레임을 검사한다. 위상 0일 때 두 편의 마지막 완전 마디 경계 예시는 45.128205초와 69.743590초다. 음성·사건 효과음은 원래 끝까지 유지한다. 최종 −14 LUFS 목표, true peak와 clipping을 함께 기록한다.
4. **사실과 퀴즈.** HUD 배속이 극적 연출인지 사실 수치인지 구분하면서도 화면에 사실처럼 제시하는 배속·숙성 시간·도수 다이얼 값과 범위·토큰 관계·라벨·퀴즈 정답은 앞서 실제 렌더된 문구와 동일한 승인 주장, 값·단위·대상을 요구한다. 무관한 승인 claim, 철회, 샘플 모드 우회, 모델 출처칩 주입, 퀴즈에서만 등장하는 답을 차단하는 시험을 추가한다. 수업의 숫자 가격 금지, 샘플 계약에 있는 금액 없는 수준 표기, 첫 질문·마지막 투표·직전 검색 규칙도 유지한다.
5. **통합과 권리.** 미추적 파일까지 보존한 상태로 최신 main과 기존 변경을 합친다. 충돌이 예상되는 `config.py`를 대조하고, `supabase/local/jjeri_class.sql`의 기존 0090 기준 및 `jjeri_generation.sql`의 0091 기준 두 후보를 최신 로컬 기반에서 함께 확인한다. 두 형식의 SQL/워커 게시 차단, 기존 밈·수업·리포트 회귀, ledger 키·SHA·권리와 크레딧 교체를 확인한다. 새 출력에서 예전 CC BY 곡이나 그 곡의 크레딧이 사용되지 않아야 한다.

### 로컬 구현과 검증 기록

격리 경로는 C:/Users/임준혁/AppData/Local/Temp/jjeri-formats-main-6e5fe253이며 HEAD는 eaafa47이다. 공유 워크트리의 추적·미추적 후보를 읽어 격리본에만 합쳤다. config.py는 main의 owned_track·HyperFrames 설정과 기존 째리 설정을 함께 보존했다. 변경은 작업 중인 격리본에 있으며 번호 없는 기존 SQL 후보에 두 렌더 형식과 워커 능력 확인을 추가했다.

| 단계 | 구현과 로컬 증거 |
|---|---|
| M1 해부 | 입력 지시서 → 음성 시간표 → 등록된 세계·부품·카메라·라벨·HUD·퀴즈 → 공용 HyperFrames 실행. 정답의 내레이션 문구와 음원 SHA-256을 함께 확인한다. 원본 exporter가 문장 상대라고 표시했지만 실제로 세계 원점에서 시작하는 일부 사건은 골든 호환표로 명시했다. 퀴즈는 39.32초를 보존했다. |
| M1 수업 | 기존 12종 슬롯·타이밍·근거 검사와 새 hf_templates/jjeri-class를 연결했다. 두 형식은 로컬 GSAP·글꼴, 공용 CLI·비밀 필터·원자적 파일 쓰기와 결과 검증을 쓴다. 밈이 쓰던 실행 계약과 리포트 렌더 경로를 유지한다. |
| M1 영상 대조 | 해부 46.62초와 수업 71.34초. 모든 세계·장면과 문장 시작 오차 0초였다. 실제 30fps MP4의 해부 14장, 수업 12장을 같은 시각에서 비교했다. 최소 SSIM 해부 0.980682, 수업 0.984799. 렌더 결과는 동일 이미지 판정 보조로 사용하고 디자인 소유자 판정을 별도로 남긴다. 해부 검사의 고의 짧은 HUD 경고 2건을 유지했다. |
| M1.5 자체곡 | ledger에서 소유·해시가 확인된 sooljjerigo-groove-117만 쓰고 PCM 48kHz에서 10.103410–18.308538초를 잘라 반복한다. 접합의 양쪽 4ms에 감쇠를 적용해 샘플 불연속을 줄이되 마디 길이와 위상을 보존한다. 마지막 완전 마디 전 1초를 페이드하고 남는 구간은 음성·효과음을 이어 간다. 실제 디코딩 저역과 표시·효과음의 차이는 별도 JSON으로 남긴다. |
| M2·M3 | 해부는 2~5개 세계, 반복 세계의 독립 ID, 부품·토큰·동사와 참조, 자막 한도, 가격·건강 효능 차단, 퀴즈 답의 이전 발화·표시, 고정된 마지막 반복을 검사한다. 승인된 인용의 해당 문구와 값·단위를 대조하는 보수적 일치 규칙과 drinks_script_check를 적용한다. 등록된 각 세계의 안무 순서와 문장 칸은 고정 계약이다. 가짜 응답 최초 실패→한 번의 교정, 근거 철회 후 생성 거절을 검사한다. |
| M4 | 오크통 프로필, 나무 결, 금속 띠, 잘린 측면과 들리는 뚜껑을 등록했다. 카메라·토큰·제목을 바꾼 구조 시험을 원래 음성과 분리했다. 기존 음성과 같은 문구로 그림 구조만 바꿨으며 새 주제 영상의 근거·디자인 채택을 의미하지 않는다. |
| M5 | 전용 무료 요청, 렌더러별 임대 자격, 취소·재시도, 근거 철회, 기존 계획 해시 및 자산/QA와 소유자 게시 차단을 로컬 DB에 연결했다. SQL 후보와 승인된 제작안의 지시서가 둘 다 있을 때만 화면에 선택지가 열린다. |

로컬 명령은 아래와 같다. STEP을 바꿔 실행하며 check와 render는 별도 명령이다.

```text
python -m scripts.jjeri_formats build anatomy golden renders/anatomy-golden-project
python -m scripts.jjeri_formats check anatomy golden renders/anatomy-golden-project
python -m scripts.jjeri_formats render anatomy golden renders/anatomy-golden-project --out renders/evidence/jjeri-anatomy-golden.mp4 --workers 3
python -m scripts.jjeri_formats build class golden renders/class-golden-project
python -m scripts.jjeri_formats check class golden renders/class-golden-project
python -m scripts.jjeri_formats render class golden renders/class-golden-project --out renders/evidence/jjeri-class-golden.mp4 --workers 3
python -m scripts.jjeri_formats build anatomy owned renders/anatomy-owned-verified-project
python -m scripts.jjeri_formats check anatomy owned renders/anatomy-owned-verified-project
python -m scripts.jjeri_formats render anatomy owned renders/anatomy-owned-verified-project --out renders/jjeri-anatomy-owned.mp4 --workers 2
python -m scripts.jjeri_formats build class owned renders/class-owned-verified-project
python -m scripts.jjeri_formats check class owned renders/class-owned-verified-project
python -m scripts.jjeri_formats render class owned renders/class-owned-verified-project --out renders/jjeri-class-owned.mp4 --workers 2
python -m pytest -q tests/test_jjeri_formats_engine.py tests/test_jjeri_compositions.py tests/test_jjeri_queue.py tests/test_hf_render.py
bash scripts/smoke.sh
```

측정 스크립트는 scripts/jjeri_formats_evidence.py와 scripts/jjeri_formats_signal.py다. 첫 스크립트는 비교 프레임, PTS, 클리핑 및 LUFS를 기록한다. 둘째는 동일 지역의 첫 검출 가능 변화와 디코딩 믹스의 저역·효과음 상관 후보를 기록한다. 상관 추정과 사람의 청감은 별도다. 해부 HUD의 후속 단계는 한 박씩 구동하며, 각 단계의 한 프레임 판정은 실제 측정에 따른다.

외부 조건은 소유자 시청·청취, 승인된 실제 새 주제와 인용 일치, 무료 Edge의 실행 환경, 운영 등록부·실제 적용과 독립 검사다. 외부 서비스로 자료를 올리거나 게시하지 않았다. 롤백하려면 두 새 요청을 끄고 해당 렌더러의 대기·실행 작업을 취소·확인하며, 결과와 원장은 보존한다.

#### 최종 자체곡과 큐 증거

| 파일 | 컨테이너 | 시작·마지막 영상 PTS | 시작·마지막 오디오 PTS | LUFS / dBTP / 클리핑 |
|---|---|---|---|---|
| renders/jjeri-anatomy-owned.mp4 | 46.633333초 | 0 / 46.600000 | 0 / 46.616000 | −14.0 / −1.8 / 0 |
| renders/jjeri-class-owned.mp4 | 71.366667초 | 0 / 71.333333 | 0 / 71.329333 | −14.1 / −1.5 / 0 |

- 음원 AAC는 24.047초다. 출력에 사용한 PCM 베드의 실제 끝은 해부 45.128208초, 수업 69.743583초이고 접합 양끝 및 페이드 끝은 0 샘플이다. 렌더의 마지막 영상·음성 PTS는 베드 끝 뒤에도 이어진다. 음원과 나레이션 글·SHA 확인 로그는 renders/evidence/owned-bed-pcm.json과 renders/evidence/voice-and-source.json에 있다.
- 해부의 항아리·체 의성어는 소리와 함께 각각 −25.458ms, +105.604ms에서 재조정했다. 디코딩한 영상의 첫 검출 변화와 저역 상관 후보의 차이는 각각 −13.542ms와 −23.937ms였다. 효과음 상관 후보는 각각 11.313초와 22.612초였다. 두 후보는 해당 저역 박과 각각 한 프레임 이내다. 체의 효과음 후보와 표시 자체의 간격은 약 45ms이고, 두 사건 모두 청감 판정 대기다.
- 해부 HUD 첫 시각은 자막 경계 때문에 보존했다. 후속 단계는 0.5128205초씩 배치했으며 첫 단계 및 후속 1·2단계의 측정 오차는 한 프레임 안, 후속 3단계는 약 37.9ms다. 잔 의성어·칩과 수업 도장은 이동 상한 밖이어서 시각을 보존했다. 수업 도장의 효과음은 최종 혼합에서 상관 신호가 약해 분리 시각을 확정하지 않았다.
- 각 사건과 프레임은 renders/evidence/anatomy-owned-verified/alignment-measured.json, renders/evidence/class-owned-verified/alignment-measured.json 및 같은 디렉터리의 비교 JPG에 있다. 골든은 renders/evidence/anatomy-golden 및 class-golden에 보관한다. 오크통 구조 변이 영상과 프레임은 renders/evidence/barrel-structure.mp4와 barrel-frame.jpg다.
- 수업은 JJERI_LOCAL_REAL_RENDER=1 python -m pytest -q tests/test_drinks_loop_e2e.py -k jjeri 로 가짜 모델 응답과 저장한 음성을 바탕으로 실제 로컬 렌더, 파일 저장, QA 등록을 완료했다. 해부는 별도로 렌더한 실제 MP4를 로컬 워커 렌더 대역에 넣어 등록·음량 재측정·0원 원장·게시 상태 차단을 확인했다. 최신 RPC에서 구버전 워커는 두 째리 형식의 신호가 없으면 큐를 건너뛴다.
- 실제 Next.js와 Chromium의 /drinks/production 경로에서 두 형식 옵션, 해부 미리보기, 실제 PGlite 신청, 실패 사유를 검증했다. 로컬 REST 시험 다리와 가짜 운영자 쿠키를 사용했고 자동 디스패치 자격 증명은 비웠다. 화면은 renders/evidence/production-anatomy.png와 production-error.png, 로그는 browser-rehearsal.log다.
- renders/는 격리본의 로컬 결과 디렉터리로 Git에서 제외했다. 빌드 명령을 다시 실행할 때는 새 프로젝트 디렉터리를 지정한다.

### 최종 smoke

- 격리본 eaafa47에서 Git Bash에 Python 가상환경·Node·FFmpeg 경로를 넣고 bash scripts/smoke.sh를 실행했다. 최종 줄은 `SMOKE OK 6/6`이고 총 1,241초가 걸렸다.
- Python 5,915건 통과·4건 건너뜀(가드 14건 이하), 웹 Node 608건 통과, 주류 순환 PGlite E2E 33건 통과, TypeScript 및 ESLint 통과다. 최종 실행에서 밈 임시 폴더 간헐 실패는 재현되지 않았다. 원본 로그는 renders/evidence/smoke-verified.log에 있다.

### 독립 코드 검사
- Codex 코드 리뷰는 세션 사용 한도로 생략했다(Orca task_f1c6dcb91981, 한도 안내 21:45, 시간대는 안내에 미표기). 앞서 받은 Codex 계획 리뷰와 구분한다. Fable 독립 검사 결과는 대기다.


### Fable 재검사 반영

기준 보고서는 `harness-review-jjeri-formats.md`다. 최종 커맨드와 두 출력의 비교표, smoke 전후 소스 SHA-256 및 로그는 `renders/evidence/review-acceptance.md`에 수록한다. 위의 최초 smoke 기록에는 검사 중 변경이 있었으므로 이 재검사의 완료 증거로 사용하지 않는다.

| 판정 | 반영 및 경계 |
|---|---|
| ❌1 튜닝 정본 | `engine/config.py`의 자체곡·음량·표시 지연·SFX 측정 규칙을 두 형식이 사용한다. Golden fixture는 원래 음향·화면 재생을 위해 기존 값 묶음을 사용한다. 음원 상관으로 박을 대체하지 않고 저역 에너지 피크와 원본 시작 프록시, 격자를 각각 기록한다. |
| ❌2 최종 파일 smoke | 격리본의 변경된 추적·미추적 파일 목록과 SHA-256을 검사 전후 대조한다. 기존 밈 임시 디렉터리 시험 실패가 나오면 로그에 원래 이름을 유지한다. |
| ⚠1 음량 여유 | 째리 목표는 −15 LUFS로 설정하고 기존 허용 범위를 유지한다. 공용 렌더의 밈 기본값은 그대로다. |
| ⚠2–3 해부 생성 및 제작 | 기존 운영자 API와 결재·lease·해시 경로에 해부 선택을 연결했다. 두 스위치는 기본 꺼짐이고, 이전 워커는 해부 생성 요청을 가져가지 않는다. 무료 검증에서만 공급자 응답과 저장된 동일 발화로 대체한다. |
| ⚠4 인용 의미 | 영어 원문과 한국어 번역 대응은 이번 보장 밖이다. 실제 새 주제의 원문과 해부 지시서 의미 대조는 사람 판정으로 남긴다. |
| ⚠5 게시 | 해부 워커의 소유자 대기 문구와 분기 검사를 추가한다. SQL 후보의 해부 포맷 게시 차단을 검증한다. |
| ⚠6 퀴즈 | 질문의 가격·건강·형식 검사와 답의 화면·음성 인용 대조를 유지한다. 질문·오답 선택지의 전제 확인은 사람이 한다. |
| ⚠7 SQL wrapper | 이후 RPC를 대체할 때 째리 가드 보존 순서를 후보 주석과 deviation에 기록한다. 운영 등록과 번호는 대기다. |
| ⚠8 중복 설정 | 째리 loudnorm을 적용했다. 기존 HF 환경 정리 중복 및 Actions 리터럴은 별개 변경 범위로 유지한다. |
| ⚠9 deviation | 해부, 승인, 인용과 운영 경계를 추가한다. |
| ⚠10 모델 | 기존 공용 결재 모델과 금액 산정을 유지한다. 실제 유료 요청은 실행하지 않았다. |
| ⚠11 회귀 원인 | 해부 금지 항목 테스트가 기대하는 오류 사유를 직접 확인한다. |


### Fable 독립 재검사와 Actions 배선

- 독립 보고서 `harness-review-jjeri-formats-recheck.md`의 판정은 **PR 진행 가능(❌ 0건)**이다. 판정 대상은 `eaafa47` 격리본의 당시 변경 파일 69개다. Fable이 체 효과음·HUD 5단계·자체곡 출력 재조립과 직전 smoke 해시를 독립 확인했고, 관련 13개 파일 284건을 재실행했다. 직전 `SMOKE OK 6/6` 및 5,919건/4건 건너뜀의 증거는 `renders/evidence/review-smoke-final.log`와 `review-smoke-{before,after}.json`에 있다.
- 마지막 운영 주의 사항인 Actions 배선을 반영했다. `.github/workflows/drinks-develop.yml`의 `jobs.develop.env`는 일반/해부 생성 플래그를 각각 저장소 `vars`에서 읽고 누락 시 `'0'`을 사용한다. `tests/test_workflow_wiring.py`는 두 값이 작업 단계까지 전달되는지와 워커 진입점의 네 조합을 가짜 RPC로 검사한다. 일반 `0`이면 해부 값과 무관하게 생성 능력 없음, 일반 `1`·해부 `0`이면 수업만, `1/1`이면 수업과 해부 생성 요청을 처리할 수 있다. 운영 플래그를 활성화하는 절차는 별도다.
- **브라우저·로컬 근거** — 기존 Next.js/Chromium 테스트에서 운영자 401, 결재 확인, 해부 미리보기, 승인·재생성을 확인했다(`renders/evidence/anatomy-generation-browser-final.log`). 기존 로컬 PGlite 요청과 실제 HyperFrames 큐에서 모의 모델·저장 발화로 영상 등록·QA·0달러·게시 예약 차단을 확인했다(`queue-anatomy-final.log`). 이번 배선 변경은 정적 YAML과 실제 워커 시작의 가짜 RPC 조합으로 검사한다.
- **남은 검증** — Fable이 기록한 골든 MP4와 프레임은 유지했고 골든 HTML 재조립으로 대조했다. 골든 연출 오프셋은 기존 값을 유지했다. 수업 도장 등 약한 믹스 증거와 소유자 청취·실제 새 주제 및 영어 원문/한국어 의미 대조는 대기다. 실제 Actions 러너 변수 전달·Node/Chromium, 운영 SQL 등록부·번호·wrapper 가드 보존, 실제 Edge TTS와 유료 모델 호출은 미검증이다.
- **배선 변경 후 최종 근거** — 사용한 PATH와 전체 `bash scripts/smoke.sh` 마지막 줄은 `renders/evidence/actions-wiring-smoke.log`에 있다. 실행 전후의 HEAD, 인덱스, 변경 파일 SHA-256은 `actions-wiring-{before,after}.json`과 `actions-wiring-integrity.log`로 비교한다. 이번 소스의 결과·밈 간헐 시험 기록·변경 단위별 커밋 파일 묶음은 `renders/evidence/actions-wiring-handoff.md`에 있다. 1,241초 옛 smoke는 이 판정의 근거에서 제외한다.
- **머지 전 조건** — 독립 Fable 판정 범위 이후 변경한 YAML·테스트·이 기록은 별도 검토하고, 대상 main의 차이와 종속 후보를 맞춘다. 운영 활성화는 등록부·마이그레이션 순서·wrapper 보존, 워커/웹 플래그와 런타임 검증, 비용·공개 승인 조건을 충족한 뒤 한다. 현재 변경은 격리본 작업 파일의 상태다.
