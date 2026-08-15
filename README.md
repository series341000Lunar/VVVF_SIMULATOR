# VVVF GTO Simulator MK1

PC 안에서 철도용 VVVF 변조를 계산하고, 파형과 스펙트럼을 시각화하며,
합성된 가상 모터음을 실시간 재생하기 위한 Python 연구용 시뮬레이터입니다.
녹음된 MP3/WAV의 속도를 바꿔 재생하는 프로그램이 아닙니다.

> **현재 상태: Stage A** — 외부 프로파일, 속도/스로틀/운전 상태 GUI,
> 전기 주파수와 현재 변조 구간 상태 표시까지 구현되어 있습니다.

## 매우 중요한 데이터 고지

`profiles/mck01c_research.json`은 다음 목적의 초기 개발용 데이터입니다.

**RESEARCH / PLACEHOLDER PROFILE — NOT VERIFIED MCK01C DATA**

속도 경계, 캐리어 주파수, 펄스 수, 주파수 변환 계수, 음향 공진값은 실제
Toshiba MCK01C의 검증된 수치가 아닙니다. 향후 조사된 자료는 프로그램 코드가
아닌 JSON 프로파일에 입력하도록 설계합니다.

## 요구 환경과 설치

- Windows 10/11
- Python 3.11 이상
- PySide6
- 이후 단계용 NumPy, SciPy, sounddevice, pyqtgraph

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

다른 프로파일은 `--profile`로 선택할 수 있습니다.

```powershell
python main.py --profile .\profiles\mck01c_research.json
```

## Stage A 기능

- 0.0~120.0 km/h 속도 슬라이더(0.1 km/h 단위)
- 0~100% Power / Throttle 슬라이더
- `POWERING` / `COAST` 상태 선택
- 속도 × 프로파일 계수로 계산하는 교체 가능한 전기 주파수 모델
- 외부 JSON에 따른 현재 ASYNC/SYNC/ONE_PULSE 구간 선택과 상태 표시
- Carrier Frequency, Pulse Count, Modulation Index, Fundamental Frequency 표시
- 변조 구간이 달라질 때만 console transition log 출력
- 미검증 MCK01C 데이터 경고를 GUI에 항상 표시

Stage A에서 화면에 보이는 변조 모드는 **프로파일 구간 선택 결과**입니다.
실제 switching waveform 생성은 Stage B/C에서 구현합니다.

## 프로파일 구조

필수 최상위 필드는 `name`, `verified`, `description`, `data_notice`,
`motor_frequency_model`, `powering`입니다. `powering` 구간은 0 km/h부터
끊김 없이 이어져야 하며 마지막 끝점만 포함 구간으로 처리합니다.

- `ASYNC_PWM`: 양수 `carrier_hz` 필요
- `SYNC_PULSE`: 양의 정수 `pulse_count` 필요
- `ONE_PULSE`: `pulse_count`가 반드시 1

현재 motor model은 아래의 명시적인 placeholder 선형식입니다.

```text
electrical_frequency_hz = vehicle_speed_kmh × electrical_hz_per_kmh
```

향후 차륜 직경, 기어비, 모터 극수를 반영하는 모델로 `vvvf/motor_model.py`를
교체할 수 있으며 UI에는 계산식이 들어 있지 않습니다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

프로파일 JSON loading/오류 처리, 19.9→20.1 km/h를 포함한 경계 선택,
상태 모델의 주파수·변조율·COAST 처리를 검증합니다.

## 다음 단계와 알려진 제한

- Stage B: 3상 기준파와 실제 ASYNC PWM, waveform graph
- Stage C: 실제 switching 차이를 만드는 SYNC pulse와 ONE_PULSE
- Stage D: motor acoustic model, limiter/volume/ramp를 포함한 48 kHz audio
- Stage E: FFT spectrum과 profile reload
- Stage F: 전체 정리와 최종 검증

현재는 audio stream, START/STOP, waveform, FFT, profile reload가 없습니다.
CAN Bus, OBD-II, 실제 gate driver나 인버터/차량 제어 및 고전압 hardware
output은 이 프로젝트의 MK1 범위 밖입니다.
