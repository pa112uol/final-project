# Pool comparison: mpd-pools vs mpd-pools-nombid

## all (200 cases)

| Metric | mpd-pools | mpd-pools-nombid | Difference [95% CI] |
| --- | --- | --- | --- |
| track_recall_rankable | 0.029 | 0.027 | +0.002 [-0.002, +0.007] |
| artist_recall_rankable | 0.071 | 0.066 | +0.005 [-0.002, +0.012] |
| track_precision | 0.010 | 0.011 | -0.001 [-0.005, +0.004] |
| track_ndcg | 0.033 | 0.034 | -0.010 [-0.025, +0.005] |
| artist_precision | 0.058 | 0.060 | -0.002 [-0.013, +0.008] |
| artist_ndcg | 0.181 | 0.226 | -0.048 [-0.090, -0.007]* |
| ild | 0.650 | 0.585 | +0.065 [+0.030, +0.099]* |
| unique_artists | 7.885 | 7.465 | +0.420 [+0.215, +0.630]* |
| seed_coverage | 0.875 | 0.910 | -0.035 [-0.080, +0.005] |
| seed_balance | 0.593 | 0.554 | +0.039 [-0.026, +0.107] |
| empty_list_rate | 0.005 | 0.015 | -0.010 [-0.025, +0.000] |

## seed_resolved (172 cases)

| Metric | mpd-pools | mpd-pools-nombid | Difference [95% CI] |
| --- | --- | --- | --- |
| track_recall_rankable | 0.029 | 0.026 | +0.003 [-0.002, +0.008] |
| artist_recall_rankable | 0.069 | 0.063 | +0.006 [-0.002, +0.014] |
| track_precision | 0.012 | 0.012 | -0.001 [-0.006, +0.004] |
| track_ndcg | 0.037 | 0.038 | -0.011 [-0.028, +0.007] |
| artist_precision | 0.058 | 0.061 | -0.003 [-0.015, +0.009] |
| artist_ndcg | 0.176 | 0.226 | -0.055 [-0.103, -0.008]* |
| ild | 0.661 | 0.586 | +0.075 [+0.035, +0.114]* |
| unique_artists | 7.994 | 7.506 | +0.488 [+0.250, +0.733]* |
| seed_coverage | 0.872 | 0.910 | -0.037 [-0.085, +0.005] |
| seed_balance | 0.595 | 0.554 | +0.042 [-0.031, +0.112] |
| empty_list_rate | 0.000 | 0.012 | -0.012 [-0.029, +0.000] |
