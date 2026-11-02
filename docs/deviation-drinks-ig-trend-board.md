# 인스타 트렌드 보드·밈 보드 — 구현 기록 (2026-11-02)

총괄 계획 1단계 ⓑ. 기획은 `docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md` §6·§8 이다.
**이 기능은 아직 돌고 있지 않다.** 코드와 파일만 있다. 아래 "켜려면"을 끝내야 움직인다.

## 만든 것

| 무엇 | 어디 | 하는 일 |
|---|---|---|
| 표·함수 | `supabase/migrations/0063_drinks_ig_trend_board.sql` | **파일만 있다. 운영 DB 에 적용하지 않았다.** |
| 매일 수집 | `engine/drinks_ig_trends.py` | 인기 음원(T1)·관찰 계정(T2)·운영자 링크(T3)를 공식 API 로 읽는다. 0원. |
| 자동 실행 | `.github/workflows/drinks-trend-board.yml` | 매일 KST 07:30. **main 에 머지된 뒤에만 돈다.** |
| 화면 | `/drinks/memes` (메뉴: 수집 → 밈 보드) | 카드, [쓰자]·[넘기기]·[나중에], 오르는 음원, 링크 넣기, 관찰 계정 체크 |
| 시험 | `tests/test_drinks_ig_trends.py`, `web/lib/drinks/igTrends*.test.ts` | 네트워크·토큰 없이 돈다 |

기존 `drinks_trends`(네이버 카페·뉴스, 표 `drink_trend_*`, 화면 `/drinks/trends`)는 다른 기능이다. 건드리지 않았다.
`engine/drinks_fetch.py` 는 한 곳만 바꿨다. HTTP 오류 응답 본문을 `FetchError.error_body` 로 넘긴다(토큰 만료와 계정 없음을 구별하려고). 기존 호출부 동작은 같다.

## 켜려면 (운영자 결재 대상)

1. **GitHub 비밀 등록.** 이름만 적는다.
   - `SOOLJJERIGO_FB_TOKEN` — 필수. 2026-10-31 문서에 등록됐다고 적혀 있다. 이 저장소에 실제로 있는지는 `gh secret list` 로 확인할 것.
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — 필수. 다른 워크플로와 같은 것이다.
   - `ARXIV_CONTACT`, `OPENALEX_MAILTO` — 있으면 요청 머리글의 연락처로 쓴다. 다른 워크플로와 같은 것이다.
   - 인스타 계정 ID 는 비밀이 아니라 `config.DRINKS_IG_USER_ID` 에 기본값으로 있다. 다른 계정으로 돌릴 때만 환경변수 `DRINKS_IG_USER_ID` 를 넣는다.
2. **0063 운영 적용.** 적용 전에는 화면이 "0063 이 운영 DB 에 아직 없습니다"라고 말한다. 적용 전에 크론이 돌면 그 실행은 실패로 끝난다.
3. **main 머지.** 그 전에는 크론이 없다.
4. **화면에서 관찰 계정 체크.** 씨앗은 전부 후보 상태다. 체크 전에는 T2 가 아무도 안 읽고, 정상 관측일도 생기지 않는다.
5. **아래 "확인 안 된 것"의 읽기 요청을 한 번 돌려 본다.** 칸 이름이 하나라도 틀리면 T2 가 통째로 실패할 수 있다.

## 규칙을 어디서 지키나

- **실패가 0건처럼 보이지 않는다.** 수집원마다 날짜마다 상태 5종(`ok`·`ok_empty`·`partial`·`failed`·`not_run`)을 남긴다. 상태와 숫자가 어긋나면 DB 가 저장을 거부한다. 안 돈 날은 다음 실행이 `not_run` 으로 채우고, 화면은 그 전이라도 기록 없는 날을 끊긴 날로 센다.
- **정상 관측일이 아니면 카드가 안 바뀐다.** 워커가 안 부르고, 불러도 DB 가 `not_normal_day` 로 거부한다. 관측값은 그날도 저장한다.
- **토큰을 빼면:** 세 수집원 모두 `failed`, 사유 `token_missing`. 외부 호출 0회. 카드 그대로. 워크플로는 빨갛게 끝난다. 합격 시험은 `test_acceptance_removed_token_...`(파이썬)와 `합격 시험(§9 P1 시뮬레이션)`(PGlite)이다. **실제 토큰을 뺀 운영 시험은 아직 안 했다.**
- **남의 영상을 저장하지 않는다.** 영상 주소를 넣을 칸이 표에 없다. API 가 주소를 줬는지만 참·거짓으로 남긴다. 음원 파일 주소(`download_url`)도 버린다. 캡션은 첫 줄만 남긴다(§6-7 의 "링크·수치·형식 설명·표지 주소" 범위에 맞췄다).
- **영상 칸은 근거 없이 못 채운다.** 비트 수·컷 길이·반전 시점·첫 1.5초·음악 동기화는 근거가 `video`·`operator` 가 아니면 코드가 지우고 DB 도 거부한다. 지금은 분석을 안 하므로 운영자가 직접 넣을 때만 찬다.
- **[쓰자]는 기록만 한다.** 분석·Apify·구매로 이어지는 길이 없다. §6-1 의 클릭 승인은 연결하지 않았다. 화면이 그렇게 말한다.
- **T4(Apify)는 자리만 있다.** 표의 상태 어휘에 `t4` 가 있을 뿐이다. 기록 함수가 받지 않고, 코드에 Apify 호출이 없다.
- **토큰:** Authorization 헤더로 보낸다. `debug_token` 만 입력값이 주소에 들어가므로 httpx 요청 로그를 끄고, 오류·로그에는 사유 코드만 남긴다. 다음 쪽은 응답의 주소를 따라가지 않고 값만 꺼내 다시 만든다.

## 기획이 정하지 않아 제가 정한 것

| 정한 것 | 이유 | 바꾸려면 |
|---|---|---|
| 노래는 카드를 만들지 않는다. 이름 있는 원본 소리만 카드가 된다. 노래는 "오르는 음원" 목록에만 나온다 | 하루 100곡이 카드로 쏟아진다. 인기 밈 24편 중 22편이 원본 소리다 | `config.DRINKS_IG_CARD_AUDIO_TYPES` |
| 새 카드 상한 하루 30장. 넘친 수는 실행 결과(`cards_capped`)와 로그에만 남고 다음 날 다시 판정한다 | 3일째에 목록 전체가 "3일 연속"이 되는 날 대비 | `DRINKS_IG_MAX_NEW_CARDS_PER_RUN` |
| 첫 관측일에는 음원을 "처음 들어옴"이라고 하지 않는다 | 전부 처음 보는 것이다 | `rising_audio_reason` |
| 음원 "3일 연속"은 달력이 아니라 **T1 이 `ok` 였던 날**로 센다 | 실패한 날이 연속을 끊거나 채우면 안 된다 | 〃 |
| 기준선 표본은 **릴스·나이 구간당 값 하나**(그 구간의 가장 최근 값), 최근 60일 | 같은 릴스를 매일 세면 표본이 부풀려진다. §6-3 의 "릴스가 8개" 표현에 맞췄다 | `DRINKS_IG_BASELINE_LOOKBACK_DAYS` |
| 뜨는 릴스를 판정할 때 그 릴스 자신도 기준선 표본에 넣는다 | 문서 문구 그대로다. 중앙값이라 영향이 작다 | `judge_reels` |
| 기준선이 0 이면 뜨는 릴스로 보지 않는다 | 3 × 0 이면 전부 뜨는 릴스가 된다 | `judge_reel` |
| 활성 계정 0개는 정상 관측일이 아니다. T2 는 `ok_empty`(시도 0) | 성공률을 말할 수 없다. 그래서 체크 전에는 사흘 뒤 "관측 중단"이 뜨고, 화면이 이유를 같이 말한다 | `is_normal_day` |
| T1 이 `partial`·`ok_empty` 면 정상 관측일이 아니다 | §6-2 가 "T1 이 `ok`" 라고만 했다 | 〃 |
| 정상 관측일이 아닌 날은 **새 카드도 만들지 않는다.** 관측만 저장하고 다음 정상일에 다시 판정한다 | 일부만 본 날의 신호로 카드를 늘리지 않으려고 | `run` |
| "오르는 중"은 카드가 생긴 다음 날부터 2일 연속 증가. 생긴 날의 0→1 은 증가로 안 센다 | v1 §6-6 해석 | `next_lifecycle` |
| 식음 판정의 "활동"에 **그 음원이 오늘 목록에 있음**을 넣었다 | 음원 카드는 자동으로 예시가 안 붙어서, 안 넣으면 목록에 그대로 있어도 7일 뒤 식는다 | 〃 |
| 3일 연속 음원은 "오르는 중"이 한 번만 된다. 다음 날 증가가 없으면 "정점" | 안 그러면 목록에 있는 동안 영원히 오르는 중이다 | 〃 |
| 식은 카드에 활동이 다시 생기면 "새로 뜸"으로 돌아가고 보관이 풀린다 | 기획에 없다 | 〃 |
| 정상일 판정 동결(§6-6): 오늘 기록이 없으면 오늘은 세지 않는다 | 07:30 전에 화면을 열어도 하루가 더 세지지 않게 | `freeze_state`, `boardHealth` |
| T3 링크는 조회수 배수와 상관없이 카드가 된다 | 사람이 봤다는 것 자체가 신호다. T3 로 찾은 릴스는 그 한 건만 저장하고 그 계정의 다른 릴스는 저장하지 않는다 | `link_elements` |
| 계정을 뺐다가 다시 체크하면 첫 관측일을 새로 잡는다 | 그동안 올라온 릴스가 한꺼번에 새 예시가 되는 것을 막으려고 | `drinks_ig_watch_action` |
| 운영자가 칸을 직접 넣는 작은 입력 칸을 넣었다 | §6-5 의 정밀 틀 승격 두 번째 길이다. 없으면 분석 전까지 정밀 틀이 될 길이 없다 | 화면만 빼면 된다 |
| 후보 씨앗 11개(밈 5·술 4·설명형 2). 기획의 40~60개가 아니다 | 문서에 실측 기록이 있는 이름만 넣었다. 나머지는 이름을 추측해야 하고, 존재 확인 호출을 이번에 하지 않았다 | 화면에서 추가 |

## 확인 안 된 것

**실제 API 를 한 번도 부르지 않았다.** 칸 이름은 Meta 문서(2026-11-02 조회)와 저장소 문서의 실측 기록에서 가져왔다.

| 미검증 | 틀리면 |
|---|---|
| Business Discovery 가 `media_product_type`·`thumbnail_url`·`media_audio_type`·`timestamp`·`permalink`·`caption`·`media_type` 을 주는지. 문서 페이지에 이름이 나온 것은 `comments_count`·`like_count`·`view_count`·`media_url` 뿐이다 | **없는 칸을 물으면 요청 전체가 거부될 수 있다.** 그러면 T2 가 전부 `bad_request` 로 실패한다. `config.DRINKS_IG_MEDIA_FIELDS` 에서 빼면 된다 |
| `GET /ig_audio` 의 다음 쪽 값(`paging.next`·`paging.cursors.after`). 문서에 없고 메모에 "페이징 있음"만 있다 | 1쪽만 받는다. 실패로는 안 보인다 |
| `view_count` 의 정의. 문서는 "유료·자연 합산"이라고 한다 | 기준선 해석이 달라진다 |
| Authorization 헤더가 `graph.facebook.com` 에서 통하는지(`debug_token` 포함). 게시 경로는 `graph.instagram.com` 에서 실측됐다 | `debug_token` 만 안 되면 `unavailable` 로 기록되고 수집은 계속된다. 전부 안 되면 `token_expired`·`api_error` 로 실패한다 |
| `Invalid user id` 의 오류 코드(110 또는 100 으로 처리했다) | 사유가 `api_error` 로 잡힌다. 상태는 같다 |
| 연령 제한 계정. Meta 문서는 "연령 제한 전문 계정의 데이터는 돌려주지 않는다"고 하는데, 검토 문서는 dailyshot·masterofmalt 조회 성공을 적었다 | 그 계정이 실패로 잡히고 성공률을 깎는다. 빼면 된다 |
| Graph API 버전. 저장소 기본값 `v23.0` 을 그대로 쓴다 | `DRINKS_IG_GRAPH_VERSION` |
| 80% 문턱·3배·8개·7일·유사도 0.5 | 전부 첫 값이다. 2주 관측 뒤 다시 정한다(§6-3·§6-4) |

읽기 요청 확인법은 아래다. 토큰은 환경변수로만 두고, 출력·주소에 남기지 말 것.

```bash
# 칸 이름 확인 (계정 하나)
curl -s -G -H "Authorization: Bearer $SOOLJJERIGO_FB_TOKEN" \
  "https://graph.facebook.com/v23.0/17841473765861006" \
  --data-urlencode "fields=business_discovery.username(9gag){id,username,followers_count,media_count,media.limit(3){id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count,view_count,thumbnail_url,media_url,media_audio_type}}"

# 음원 목록과 다음 쪽 모양
curl -s -G -H "Authorization: Bearer $SOOLJJERIGO_FB_TOKEN" \
  "https://graph.facebook.com/v23.0/ig_audio" \
  --data-urlencode "audio_type=original_sound" --data-urlencode "user_id=17841473765861006"
```

**화면:** 시험용 가짜 데이터(로컬 PGlite)로만 열어 봤다. 운영 화면은 0063 적용 전이라 열어 볼 대상이 없다.

**아직 안 만든 것**
- 형식 분석(P1-분석, 별도 결재). 그래서 구조·표지 글자는 운영자가 넣기 전까지 비어 있다.
- 우리 술 버전 아이디어·주의 문구(LLM 이 필요하다).
- 운영자가 릴스를 음원 카드에 붙이는 버튼(§6-6 의 "운영자 확인"). 자동으로 붙지도 않는다.
- 카드 → 밈 제작 엔진 연결(4단계).
- 관찰 계정 자동 후보 제안(v1 §6-7).
- 토큰 자동 연장(§8 V-T2, 별도 결재).
- 7일 연속 `trend_runs` 기록(§9 합격 기준). 머지 뒤에만 쌓인다.

## 되돌리기

- 크론 끄기: 워크플로 파일을 지우거나 GitHub 에서 비활성화한다. 기록은 남는다. 화면은 `관측 중단`으로 넘어간다.
- 화면 끄기: `web/lib/nav.ts` 의 "밈 보드" 줄과 `web/app/drinks/memes/` 를 지운다. `actions.ts` 의 `ig_*` 네 줄도 같이 뺀다.
- 표 지우기: `0063_drinks_ig_trend_board.sql` 머리말의 되돌리기 문장을 실행한다. 기존 표는 건드리지 않으므로 다른 기능에 영향이 없다.
