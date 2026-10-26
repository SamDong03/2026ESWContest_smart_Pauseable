

NAMES = {
    "fridge_recheck": "냉장고 재확인 가설",
    "normal_meal_prep": "정상 재료 꺼내기",
    "microwave_restart": "전자레인지 재시작 가설",
    "normal_batch_cooking": "정상 여러 접시 가열",
    "normal_single_use": "정상 단일 사용 / 2초 문 열기",
    "normal_night_snack": "정상 야간 간식",
    "caregiver_visit": "보호자 방문 / 여러 사람 사용",
    "task_omission": "과제 누락 가설 / 반복과 별개",
    "prolonged_heating": "장시간 가열 / 반복과 별개",
    "sensor_duplicate": "동일 이벤트 중복 전달",
    "sensor_dropout": "센서 이벤트 누락 / 판단 보류",
    "fridge_distributed_rechecks": "2시간에 걸친 분산 재확인 가설",
    "normal_slow_meal": "정상 느린 식사 준비",
    "washer_power_recheck": "세탁기 전원 재확인 가설 / 공학적 유추",
    "normal_washer_setup": "정상 세탁기 준비 / 동일 전원 입력",
    "normal_washer_full_cycle": "정상 세탁기 한 사이클 / 자동 완료",
}


def write_study_report(output, report, summaries, registry, baseline, manifest):
    lines = ["# 시뮬레이션 결과와 기준 변경 기록", "",
             "실제 환자 기록이나 치매 진단 성능이 아니다. 연구용 모델은 운영에 배포하지 않았다.", "",
             "## 이번에 바꾼 것과 유지한 것", "",
             "| 구분 | 이전/문제 | 이번 처리 |",
             "| --- | --- | --- |",
             f"| 행동 유형의 근거 | 기존 합성 시나리오와 임상 근거의 구분 필요 | 근거 {len(registry['sources'])}개와 {len(registry['scenarios'])}개 시험 유형 연결. 수치 가정은 별도 표기 |",
             "| 학습 표본 시각 | 매시 정각 표본은 중간의 짧은 사용을 놓칠 수 있음 | 연구용 표본만 날짜별 분 위치를 순환. 실서비스의 매분 특징 생성은 그대로 |",
             "| 공통/운영 baseline 임계값 | 기존 코드의 공학적 규칙 | 변경하지 않음. 임상 기준으로 승인된 숫자 아님 |",
             "| 연구용 baseline/IF/AE | 개인 모델과 섞이면 안 됨 | 별도 합성 한 달로 연구 폴더에만 생성. 기준 baseline은 학습 구간만 사용 |",
             "| 공개 환자 자료 | 가구별 이벤트에 반복 정답 없음 | 선택한 경우 시간대 참고만. 정상 라벨/AE 학습 원본으로 쓰지 않음 |",
             "| 반복과 정상 사용 | 동일 센서 기록에 다른 원인 가능 | 완전히 같은 입력의 가설/정상 쌍을 함께 시험 |",
             "| 단일 사용 모델 오탐 | 이상 점수만으로 반복행동 승격 가능 | 실제 반복 근거 guard 결과를 별도 열에 기록. 원래 baseline/IF/AE 점수는 보존 |",
             "| 수집 누락 | 관찰 없음과 정상은 다름 | 누락을 주입한 시험에서 판단 보류. 새 실시간 고장 탐지기 구현은 아님 |",
             "| 실제 통신/제어 | 연구 결과가 실제 행동을 일으키면 안 됨 | 네트워크 없는 Docker 시험. MQTT/가전/PI 접속 없음 |", "",
             "## 실행 조건", "",
             f"- 시나리오 {report['cases']}개 = {len(registry['scenarios'])}개 유형 × {len(report['intensities'])}개 밀도 × {len(report['seeds'])}개 seed.",
             f"- seed: {report['seeds']}. low/medium/high는 환자 중증도가 아닌 생성 이벤트 밀도.",
             f"- 수치 특징 {report['model_feature_count']}개. 합성 한 달은 하루 24개 분산 표본, 각 시험은 1분 간격.",
             f"- MINDER 시간대 참고 사용: {report['public_reference_used']}. AE 최적화 수렴: {report['optimizer_converged']}.",
             "- 학습/보정/검증은 시간순 60/20/20, 경계 120분 제외. 최종 시나리오는 미래 날짜.",
             "- 가설/정상 쌍과 seed 변형은 서로 연관된 시험이다. 독립 환자 수로 세지 않는다.", "",
             "## 연구용 기준값", "",
             "아래 p95는 정상 가정 합성 **학습 구간**의 95백분위다. 환자 실측 기준이나 임상 임계값이 아니다.", "",
             "| 특징 | 합성 학습 p95 | 합성 학습 p99 |",
             "| --- | ---: | ---: |"]
    for feature in ["fridge_door_open_count_10m", "fridge_door_toggle_count_10m", "microwave_start_count_10m"]:
        stats = baseline["features"][feature]
        lines.append(f"| `{feature}` | {stats['p95']:.4g} | {stats['p99']:.4g} |")
    lines += ["", "규칙 판단은 p95 하나만 비교하지 않는다. 최소 횟수, 시간대, 패턴별 조건, 연속 경보 규칙도 기존 코드에 있다.",
              "IF/AE 임계값은 별도 합성 정상 가정 보정 구간 점수의 95/99백분위다. 점수는 치매 확률이 아니다.", ""]
    for name, values in manifest["thresholds"].items():
        lines.append(f"- {name}: attention > {values['attention']:.6g}, risk > {values['risk']:.6g}.")
    lines += ["", "## 전체 결과", "",
              "각 단계는 45분 또는 분산/장시간 사례의 135분 평가 구간에서 나온 최대 단계다. ‘가설’ 경보를 실제 환자 탐지 성공으로 세지 않는다.",
              "normal=해당 규칙/모델의 정상 범위, attention=주의, risk=높은 점수, unavailable=판단 보류.", "",
              "| 사례 | 밀도 / seed | 최대 냉장고 열기/10분 | 최대 가열 시작/10분 | 최대 세탁기 시작/2시간 | baseline | IF | AE | 반복 guard 이후 |",
              "| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |"]
    for row in summaries:
        lines.append(f"| {NAMES[row['case']]} | {row['intensity']} / {row['seed']} | {row['fridge_open_peak_10m']} | {row['microwave_start_peak_10m']} | {row['washer_start_peak_2h']} | {row['rule_max_level']} | {row['if_max_level']} | {row['ae_max_level']} | {row['guarded_max_level']} |")
    lines += ["", "## 사례별 추적 로그", "",
              "events.csv는 생성 입력, features.csv는 최근 이력 요약, scores.csv는 모든 분별 판단이다. 영문 reasons는 원래 규칙이 출력한 근거를 그대로 보존했다.", ""]
    source_map = {source["id"]: source["url"] for source in registry["sources"]}
    spec_map = {spec["id"]: spec for spec in registry["scenarios"]}
    for row in summaries:
        case = row["case"]
        directory = f"cases/{case}_{row['intensity']}_{row['seed']}"
        lines += [f"### {NAMES[case]} / {row['intensity']} / seed {row['seed']}", "",
                  f"- 생성 기록 {row['rows']}행. 시작 시각 {row['start_hour']}시. 관찰 완전성 표시 {row['history_complete']}.",
                  f"- 최근 10분 최대: 냉장고 열기 {row['fridge_open_peak_10m']}회, 가열 시작 {row['microwave_start_peak_10m']}회.",
                  f"- 평가 {row['assessment_minutes']}분. 신호 의미: {row['signal_semantics']}. 세탁기 시작/2시간 최대 {row['washer_start_peak_2h']}회.",
                  f"- 경보가 나온 분별 창 수: baseline {row['rule_alert_windows']}, IF {row['if_alert_windows']}, AE {row['ae_alert_windows']}. 서로 겹치는 창이므로 별개 행동 횟수가 아니다.",
                  f"- 가장 높은 규칙 점수의 근거: {row['rule_peak_reason']}",
                  f"- [생성 이벤트]({directory}/events.csv), [특징값]({directory}/features.csv), [분별 판단]({directory}/scores.csv), [출처/가정]({directory}/provenance.json), [상태 지속시간 진단]({directory}/observation_summary.json)."]
        refs = spec_map[case]["sources"]
        lines.append("- 근거: " + (", ".join(f"[{ref}]({source_map[ref]})" for ref in refs) if refs else "센서/정상 대조를 위한 공학적 시험") + ".")
        lines.append("")
    lines += ["## 해석과 남은 과제", "",
              f"동일 입력의 가설/정상 쌍 특징 일치: {report['all_pair_features_identical']}. 입력이 같으면 의도나 기억 실패를 알아낼 수 없다.",
              "합성 정상 holdout 경보율과 생성 가설 적중률은 임상 민감도/특이도가 아니다. 정상 요리에도 경보가 나는지 먼저 확인해야 한다.",
              "개인별 실제 정상 이력, 보호자 확인, 다인 가구/식사 맥락, 센서 가용성 확인을 확보해야 실제 보정이 가능하다.",
              "운영 모델/임계값은 자동 변경하지 않았다. 임계값을 낮추거나 높여 이 표만 좋게 만드는 튜닝도 하지 않았다.", ""]
    lines += ["세탁기 전원 가설은 실제 세탁 동작과 다르다. 연구 입력은 시연의 power→operation 어댑터를 따르며 세탁기 환자 자료를 확보한 것이 아니다.",
              "사용 지속시간은 별도 진단 JSON에만 기록했다. 기존 54개 모델 특징이나 개인 모델 가중치를 바꾸지 않았다.", ""]
    (output / "simulation_report_ko.md").write_text("\n".join(lines), encoding="utf-8")
