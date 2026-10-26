import json

import pandas as pd

GRID_FILE = "data/kma_grid.xlsx"
LOCATION_CONFIG_FILE = "location_config.json"


def choose(label, options):
    options = sorted([str(option).strip() for option in options if str(option).strip()])

    print(f"\n{label} 선택")
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option}")

    while True:
        number = input(f"{label} 번호 입력: ").strip()

        if number.isdigit():
            selected_index = int(number) - 1
            if 0 <= selected_index < len(options):
                return options[selected_index]

        print("잘못 입력했습니다. 번호를 다시 입력하세요.")


def main():
    df = pd.read_excel(GRID_FILE)

    for column in ["1단계", "2단계", "3단계"]:
        df[column] = df[column].fillna("").astype(str).str.strip()

    sido = choose("시/도", df["1단계"].unique())

    df_sido = df[df["1단계"] == sido]
    sigungu = choose("시/군/구", df_sido["2단계"].unique())

    df_sigungu = df_sido[df_sido["2단계"] == sigungu]
    dong = choose("읍/면/동", df_sigungu["3단계"].unique())

    result = df[
        (df["1단계"] == sido)
        & (df["2단계"] == sigungu)
        & (df["3단계"] == dong)
    ]

    row = result.iloc[0]
    nx = int(row["격자 X"])
    ny = int(row["격자 Y"])

    location_data = {
        "sido": sido,
        "sigungu": sigungu,
        "dong": dong,
        "nx": nx,
        "ny": ny,
    }

    with open(LOCATION_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(location_data, f, ensure_ascii=False, indent=4)

    print("\n선택한 지역:", sido, sigungu, dong)
    print("nx:", nx)
    print("ny:", ny)
    print(f"{LOCATION_CONFIG_FILE} 저장 완료")


if __name__ == "__main__":
    main()
