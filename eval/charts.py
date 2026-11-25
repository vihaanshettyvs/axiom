import matplotlib
matplotlib.use("Agg")
import pandas as pd
import matplotlib.pyplot as plt

def generate_charts(csv_path="eval/benchmark_results.csv", out_png="eval/benchmark_charts.png"):
    df = pd.read_csv(csv_path)
    g = df.groupby("mode").mean()
    fig, ax = plt.subplots(1, 3, figsize=(13, 4.2), dpi=150)
    lb = ["Brain OFF", "Brain ON"]
    ax[0].bar(lb, [g.loc["brain_off", "leak_localization_min"], g.loc["brain_on", "leak_localization_min"]], color=["#8C9BA5", "#1E3B2F"])
    ax[0].set_title("Leak Localization (min)")
    ax[1].bar(lb, [g.loc["brain_off", "total_bytes_sent"]/1000.0, g.loc["brain_on", "total_bytes_sent"]/1000.0], color=["#8C9BA5", "#1E3B2F"])
    ax[1].set_title("Downlink Data (KB)")
    ds = df.groupby("mode")["uncontrolled_debris"].sum()
    ax[2].bar(lb, [ds["brain_off"], ds["brain_on"]], color=["#B84A39", "#1E3B2F"])
    ax[2].set_title("Uncontrolled Debris")
    plt.tight_layout(); plt.savefig(out_png); print("Saved", out_png)

if __name__ == "__main__": generate_charts()
