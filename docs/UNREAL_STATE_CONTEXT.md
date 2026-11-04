# Unreal 상태·이벤트 연결과 D04·D05

D04는 추적 초기화/이벤트 신뢰성, D05는 활성 판정에 필요한 문맥 누락이다.
RUN_ONLY는 RUN만 가정하므로 경고가 생길 수 있다. 새 연결마다 사건 ID가 달라지는
기존 구조에서, 문맥을 공급하지 않은 채 재실행하면 경고 사건이 쌓인다.

이 변경은 경고 숨김·사건 삭제 대신 Unreal의 실제 RUN과 트레이 충돌 이벤트를
선택적으로 전송한다. 기본 입력과 ML 수집 코드·15필드 CSV는 바꾸지 않는다.
이벤트의 실제 UTC와 pause·RUN 해제에 멈추는 시뮬레이션 경과 시간을 함께 전송한다.
일시정지 시간을 이송 지연·미투입·예열 운전 시간으로 계산하지 않으며,
보고서와 사건의 발생 시각은 실제 UTC를 유지한다.
합성 레시피의 동일 속도/하중·진동 비교 조건은 실제 산업 PLC 검증과 구분한다.
M04(정확한 1초 간격 21표본), M19(승인 정상 기준)는 미평가로 남긴다.

## 로컬 실행

최신 서버 코드에서 **사용자 터미널로만** `TELEMETRY_UNREAL_CONTEXT_ENABLED=true`를
설정하고 기존 README 방법으로 API를 실행한다. 시험 중 `ANALYSIS_AUTO_ENABLED=false`를
사용하면 유료 자동 분석을 막을 수 있다. DB 저장 검증에는
`TELEMETRY_DB_ENABLED=true`가 필요하다. 실제 비밀 파일·키는 채팅/편집기에 넣지 않는다.

Unreal 변경도 함께 빌드한 뒤 실행한다(기본 LOCAL/RUN_ONLY는 그대로다).

```powershell
cd C:\Unreal_Projects\Weeing_Weeing_UE
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Scripts\BuildEditor.ps1 -EngineRoot 'C:\Program Files\Epic Games\UE_5.8'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Scripts\LaunchTelemetry.ps1 -Mode LOCAL -Context UNREAL_STATE -Executable 'C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe' -Project '.\Weeing_Weeing_UE.uproject'
```

1. 기본 정상 운전에서 새 D04/D05 사건이 생기지 않는지 확인한다.
2. 재실행·연결 재개에서도 새 품질 경고가 쌓이지 않는지 확인한다.
3. F6/F7 P03 주입/해제, F5 M03 주의→경고→회복을 확인한다.
4. 원천 초기화 불명·이벤트 순번 누락·비교 조건 null에서는 품질 경고가 여전히 필요하다.

기존 DB의 미회복 사건은 이 변경으로 삭제/회복하지 않는다. 운영 이력 정리는
원인·현장 확인·사용자 승인에 따라 별도로 한다. 새 연결만으로 과거 고장 회복을
추정하지 않는다. 상태 프레임에는 버퍼 상한이 있고 누락 시 D04로 중단한다.

## AWS 적용 순서

이 작업은 로컬 검증이다. AWS에는 아직 배포하지 않는다. 별도 승인 후 서버 코드를
배포한 다음, 새 Unreal 빌드를 `-Mode AWS -Context UNREAL_STATE`로
실행해야 한다. 기존 송신 인증·TLS는 유지하며 데스크탑/노트북 동시 송신을 하지 않는다.
원본 송신 토큰은 사용자 터미널의 숨김 입력에만 넣는다. IDE 자동 문맥에 열린 파일이
포함될 수 있으므로 키·토큰을 편집기나 채팅에 입력하지 않는다.

운영 compose는 승인된 배포에 맞춰 `TELEMETRY_UNREAL_CONTEXT_ENABLED=true`를
명시한다. 기존 송신 인증은 필수이며 기존 RUN_ONLY 송신 형식도 보존한다.
서버 비밀 파일을 수정하거나 출력하지 않고 기능을 활성화한다.
