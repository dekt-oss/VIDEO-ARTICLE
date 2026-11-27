- **[P2·데이터 손실] `engine/hf_render.py:202,229`** — 시스템 임시 폴더에서 `shutil.move`로 최종 파일을 옮깁니다. 출력 경로가 다른 파일시스템이면 복사로 전환되어, 중단·디스크 부족 시 부분 파일이 남거나 기존 결과가 손상될 수 있습니다. 출력 디렉터리 안에서 임시 파일을 만들고 `os.replace`로 교체해야 합니다.

- **[P2·검증 누락] `engine/hf_render.py:122-131`, `tests/test_hf_render.py:60-64`** — S1의 `--variables-file`·`--strict-variables` 계약 대신 문자열 치환과 `--strict`만 사용합니다. 템플릿에서 필수 칸이 삭제되어도 오류 없이 진행하며, 테스트도 `--strict` 존재만 확인합니다. 변수 누락·불일치 거부를 구현하고 테스트해야 합니다.

- **[P2·테스트 공백] `engine/hf_render.py:183-190`, `tests/test_hf_render.py:79-84`** — `_probe`가 FPS를 반환하지만(`engine/drinks_render.py:292`) 출력 검증에서 무시합니다. 해상도·길이·오디오가 같으면 24fps 결과도 성공 처리되어 S1의 30fps 기준을 보장하지 못합니다. FPS 검사와 거부 테스트가 필요합니다.

`origin/main...HEAD`의 코드 변경을 S1~S2와 정적으로 대조했습니다. 파일 변경 없음. 테스트·smoke·실제 렌더는 미실행으로 런타임 결과는 미검증입니다.

판정: 수정 필요 (3건)