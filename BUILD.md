# 실행파일(.exe) 빌드 가이드

세 개의 LAI 스케줄러를 각각 단일 실행파일로 빌드한다. (Windows / PyInstaller)

## 1. 사전 준비

- Python 3.13 + uv 설치
- 의존성은 `pyproject.toml`에 정의되어 있음 (`uv sync`로 설치)

## 2. exe 아이콘(.ico) 생성

`data_image`의 아이콘 PNG를 `.ico`로 변환한다. (최초 1회 또는 아이콘 변경 시)

```bash
uv run python - <<'PY'
from PIL import Image
import os
os.makedirs("build_assets", exist_ok=True)
pairs = {
    "data_image/Janssen_ico.png": "build_assets/Janssen.ico",
    "data_image/Otsuka_ico.png":  "build_assets/Otsuka.ico",
    "data_image/SHMH_ico.png":    "build_assets/SHMH.ico",
}
for src, dst in pairs.items():
    Image.open(src).convert("RGBA").save(
        dst, sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
PY
```

## 3. 빌드

```bash
uv run --with pyinstaller pyinstaller --noconfirm --onefile --windowed \
  --name "Janssen_LAI_scheduler" --icon build_assets/Janssen.ico \
  --distpath dist/Janssen Janssen_LAI_scheduler_V1.py

uv run --with pyinstaller pyinstaller --noconfirm --onefile --windowed \
  --name "Otsuka_LAI_scheduler" --icon build_assets/Otsuka.ico \
  --distpath dist/Otsuka Otsuka_LAI_scheduler.py

uv run --with pyinstaller pyinstaller --noconfirm --onefile --windowed \
  --name "SHMH_LAI_scheduler" --icon build_assets/SHMH.ico \
  --distpath dist/SHMH SHMH_LAI_scheduler.py
```

## 4. 에셋 동봉 (필수)

코드가 로고·이미지를 **현재 작업 폴더 기준 상대경로**(`data_image/...`)로 읽고,
예약 데이터(`lai_schedule_data_final.json`)도 exe 옆에 저장한다.
따라서 각 dist 폴더에 `data_image`를 함께 둔다.

```bash
cp -r data_image dist/Janssen/
cp -r data_image dist/Otsuka/
cp -r data_image dist/SHMH/
```

## 5. 배포 주의사항

- **각 폴더를 통째로 배포**한다(예: `dist/Janssen` 전체를 zip). exe만 옮기면 로고·이미지가 표시되지 않는다.
- 탐색기에서 **폴더 안의 exe를 더블클릭**해 실행한다(작업 폴더가 exe 위치로 잡혀 에셋·데이터 경로가 맞춰짐).
- 세 약제가 동일한 JSON 파일명을 쓰므로 **폴더를 분리**해 둔다(같은 폴더에 두면 데이터 공유).
- **Google Calendar 연동**: `credentials.json`을 각 exe 폴더에 넣으면 첫 인증 후 `token.json`이 생성된다.
- 서명되지 않은 exe라 첫 실행 시 Windows SmartScreen 경고가 뜰 수 있다(추가 정보 → 실행). 정식 배포 시 코드 서명 인증서 권장.

## 6. 산출물 git 제외

`build/`, `dist/`, `*.spec`, `build_assets/`는 `.gitignore`로 제외된다(바이너리/재생성 가능).
