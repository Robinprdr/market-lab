import pandas as pd


# ============================================================
# PARAMÈTRES
# ============================================================

FILE = "trades_autopsy.csv"

TEST_START = "2021-01-01"
TEST_END = "2025-12-20"


# ============================================================
# CHARGEMENT
# ============================================================

df = pd.read_csv(FILE)

df["Date"] = pd.to_datetime(df["Date"])

df = df[
    (df["Date"] >= TEST_START) &
    (df["Date"] < TEST_END)
].copy()


# ============================================================
# STRATÉGIE DE BASE
# ============================================================

# Exclusion des chutes supérieures à 4%.

df = df[
    df["Signal_Drop"] >= -0.04
].copy()


# ============================================================
# VÉRIFICATION DES COLONNES
# ============================================================

required_columns = [
    "Date",
    "Signal_Drop",
    "PnL_Pct",
    "SPY_Return",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio"
]

missing = [
    col
    for col in required_columns
    if col not in df.columns
]

if missing:

    print("\n" + "=" * 110)
    print("ERREUR : COLONNES MANQUANTES")
    print("=" * 110)

    print("\nColonnes manquantes :")
    print(missing)

    raise SystemExit


# ============================================================
# NETTOYAGE
# ============================================================

numeric_columns = [
    "Signal_Drop",
    "PnL_Pct",
    "SPY_Return",
    "SPY_Distance_SMA50",
    "SPY_Volume_Ratio"
]

for col in numeric_columns:

    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )


df = df.dropna(
    subset=numeric_columns
).copy()


# ============================================================
# FONCTION D'ANALYSE
# ============================================================

def analyse(data, label):

    if len(data) == 0:

        print(
            f"{label:<48} | aucun trade"
        )

        return None

    trades = len(data)

    win_rate = (
        data["PnL_Pct"] > 0
    ).mean() * 100

    avg_pnl = (
        data["PnL_Pct"].mean()
    ) * 100

    total_pnl = (
        data["PnL_Pct"].sum()
    ) * 100

    median_pnl = (
        data["PnL_Pct"].median()
    ) * 100

    return {
        "Label": label,
        "Trades": trades,
        "Win_Rate": win_rate,
        "Avg_PnL": avg_pnl,
        "Median_PnL": median_pnl,
        "Total_PnL": total_pnl
    }


# ============================================================
# FILTRES
# ============================================================

def get_filters(data):

    return {

        "BASE":
            pd.Series(
                True,
                index=data.index
            ),

        "SPY > SMA50":
            data["SPY_Distance_SMA50"] > 0,

        "SPY Return > -2%":
            data["SPY_Return"] > -0.02,

        "SPY > SMA50 + Return > -2%":
            (
                (data["SPY_Distance_SMA50"] > 0) &
                (data["SPY_Return"] > -0.02)
            ),
    }


filters = get_filters(df)


# ============================================================
# TITRE
# ============================================================

print("\n" + "=" * 110)
print("VALIDATION OOS — FILTRES DE RÉGIME SPY")
print("=" * 110)

print(
    f"\nPériode testée : "
    f"{TEST_START} → {TEST_END}"
)

print(
    f"Trades disponibles après exclusion des chutes > 4% : "
    f"{len(df)}"
)

print("""
IMPORTANT :
Les filtres ci-dessous sont comparés hors échantillon.

Nous ne modifions PAS leurs seuils pendant ce test.

Le but est de déterminer si les observations faites
dans l'analyse des régimes se reproduisent réellement
sur plusieurs années.
""")


# ============================================================
# 1. COMPARAISON GLOBALE
# ============================================================

print("\n" + "=" * 110)
print("1 — COMPARAISON GLOBALE")
print("=" * 110)

global_results = []


for label, condition in filters.items():

    subset = df[
        condition
    ]

    result = analyse(
        subset,
        label
    )

    if result is not None:

        global_results.append(
            result
        )


results_df = pd.DataFrame(
    global_results
)


print(
    "\n"
    f"{'Filtre':<48} | "
    f"{'Trades':>6} | "
    f"{'Win':>6} | "
    f"{'Avg':>8} | "
    f"{'Median':>8} | "
    f"{'Somme':>9}"
)

print("-" * 110)


for _, row in results_df.iterrows():

    print(
        f"{row['Label']:<48} | "
        f"{row['Trades']:>6.0f} | "
        f"{row['Win_Rate']:>5.1f}% | "
        f"{row['Avg_PnL']:>7.3f}% | "
        f"{row['Median_PnL']:>7.3f}% | "
        f"{row['Total_PnL']:>8.2f}%"
    )


# ============================================================
# 2. DELTA PAR RAPPORT À LA BASE
# ============================================================

print("\n" + "=" * 110)
print("2 — AMÉLIORATION PAR RAPPORT À LA BASE")
print("=" * 110)

base = results_df[
    results_df["Label"] == "BASE"
].iloc[0]


print(
    "\n"
    f"{'Filtre':<48} | "
    f"{'Δ Win':>8} | "
    f"{'Δ Avg':>9} | "
    f"{'Δ Somme':>10}"
)

print("-" * 110)


for _, row in results_df.iterrows():

    delta_win = (
        row["Win_Rate"]
        - base["Win_Rate"]
    )

    delta_avg = (
        row["Avg_PnL"]
        - base["Avg_PnL"]
    )

    delta_sum = (
        row["Total_PnL"]
        - base["Total_PnL"]
    )

    print(
        f"{row['Label']:<48} | "
        f"{delta_win:>+7.2f} pp | "
        f"{delta_avg:>+8.3f}% | "
        f"{delta_sum:>+9.2f}%"
    )


# ============================================================
# 3. ROBUSTESSE ANNÉE PAR ANNÉE
# ============================================================

print("\n" + "=" * 110)
print("3 — ROBUSTESSE ANNÉE PAR ANNÉE")
print("=" * 110)

years = sorted(
    df["Date"].dt.year.unique()
)


for year in years:

    print("\n" + "-" * 110)

    print(
        f"ANNÉE {year}"
    )

    print("-" * 110)

    year_df = df[
        df["Date"].dt.year == year
    ].copy()

    year_filters = get_filters(
        year_df
    )

    print(
        f"{'Filtre':<48} | "
        f"{'Trades':>6} | "
        f"{'Win':>6} | "
        f"{'Avg':>8} | "
        f"{'Somme':>9}"
    )

    print("-" * 110)

    for label, condition in year_filters.items():

        subset = year_df[
            condition
        ]

        if len(subset) == 0:

            print(
                f"{label:<48} | "
                f"{'0':>6}"
            )

            continue

        win_rate = (
            subset["PnL_Pct"] > 0
        ).mean() * 100

        avg_pnl = (
            subset["PnL_Pct"].mean()
        ) * 100

        total_pnl = (
            subset["PnL_Pct"].sum()
        ) * 100

        print(
            f"{label:<48} | "
            f"{len(subset):>6} | "
            f"{win_rate:>5.1f}% | "
            f"{avg_pnl:>7.3f}% | "
            f"{total_pnl:>8.2f}%"
        )


# ============================================================
# 4. NOMBRE D'ANNÉES POSITIVES
# ============================================================

print("\n" + "=" * 110)
print("4 — NOMBRE D'ANNÉES POSITIVES")
print("=" * 110)

for label in filters.keys():

    positive_years = 0
    negative_years = 0
    zero_years = 0

    for year in years:

        year_df = df[
            df["Date"].dt.year == year
        ].copy()

        year_filters = get_filters(
            year_df
        )

        subset = year_df[
            year_filters[label]
        ]

        if len(subset) == 0:
            continue

        total = (
            subset["PnL_Pct"].sum()
        ) * 100

        if total > 0:
            positive_years += 1

        elif total < 0:
            negative_years += 1

        else:
            zero_years += 1

    print(
        f"{label:<48} | "
        f"Années + : {positive_years} | "
        f"Années - : {negative_years} | "
        f"Années = : {zero_years}"
    )


# ============================================================
# 5. EXPORT
# ============================================================

results_df.to_csv(
    "regime_oos_results.csv",
    index=False
)


# ============================================================
# FIN
# ============================================================

print("\n" + "=" * 110)
print("FIN DE LA VALIDATION OOS")
print("=" * 110)

print("""
Le fichier suivant a été créé :

regime_oos_results.csv

Nous allons surtout regarder :

1. l'Avg PnL
2. le Win Rate
3. le nombre de trades
4. le nombre d'années positives
5. la stabilité année par année

Aucun filtre ne sera intégré à main.py avant validation.
""")