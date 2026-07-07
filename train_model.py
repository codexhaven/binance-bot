#!/usr/bin/env python3
"""
AI Phase 2 v2: Enhanced Random Forest
- 150 trees (up from 50)
- max_depth=8 (up from 6)
- 20 features (up from 9)
- Pure Python, no external dependencies
"""
import random, math, pickle, csv, sys, os, time

class DecisionTree:
    def __init__(self, max_depth=8, min_samples_split=10, max_features=4):
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.max_features = max_features
        self.tree = None
        self.feature_importances = {}

    def _gini(self, y):
        n = len(y)
        if n == 0: return 0.0
        c1 = sum(y); c0 = n - c1
        return 1.0 - (c0/n)**2 - (c1/n)**2

    def _make_leaf(self, y):
        n = len(y); c1 = sum(y); c0 = n - c1
        return {'leaf': True, 'pred': 1 if c1 >= c0 else 0, 'proba': c1/n if n > 0 else 0.0, 'n': n}

    def _find_best_split(self, X, y, feat_indices):
        n = len(y); parent_gini = self._gini(y); best_gain = 0.001; best = None
        for fi in feat_indices:
            indexed = sorted(range(n), key=lambda i: X[i][fi])
            n_thresh = min(20, n - 1)
            if n_thresh <= 0: continue
            step = max(1, (n - 1) // n_thresh)
            for t in range(step, n, step):
                left_y = [y[indexed[i]] for i in range(t)]
                right_y = [y[indexed[i]] for i in range(t, n)]
                if not left_y or not right_y: continue
                gl = self._gini(left_y); gr = self._gini(right_y)
                w = (len(left_y)*gl + len(right_y)*gr) / n
                gain = parent_gini - w
                if gain > best_gain:
                    best_gain = gain
                    thresh = (X[indexed[t-1]][fi] + X[indexed[t]][fi]) / 2
                    best = (fi, thresh, [indexed[i] for i in range(t)], [indexed[i] for i in range(t, n)])
                    self.feature_importances[fi] = self.feature_importances.get(fi, 0) + gain
        return best

    def _build(self, X, y, depth):
        n = len(y)
        if depth >= self.max_depth or n < self.min_samples_split or self._gini(y) == 0:
            return self._make_leaf(y)
        nf = len(X[0])
        fi = random.sample(range(nf), min(self.max_features, nf))
        best = self._find_best_split(X, y, fi)
        if best is None: return self._make_leaf(y)
        f, t, li, ri = best
        return {'leaf': False, 'feature': f, 'threshold': t,
                'left': self._build([X[i] for i in li], [y[i] for i in li], depth+1),
                'right': self._build([X[i] for i in ri], [y[i] for i in ri], depth+1)}

    def fit(self, X, y):
        self.feature_importances = {}
        self.tree = self._build(X, y, 0)

    def _predict_one(self, row):
        node = self.tree
        while not node['leaf']:
            node = node['left'] if row[node['feature']] <= node['threshold'] else node['right']
        return node['pred'], node['proba']

class RandomForest:
    def __init__(self, n_estimators=150, max_depth=8, min_samples_split=10,
                 max_features=4, random_state=42, class_weight=None):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.max_features = max_features
        self.random_state = random_state
        self.class_weight = class_weight
        self.trees = []
        self.feature_importances_ = None

    def fit(self, X, y):
        if self.random_state: random.seed(self.random_state)
        n = len(X); nf = len(X[0])
        if self.max_features is None: self.max_features = max(1, int(math.sqrt(nf)))
        c0 = [i for i in range(n) if y[i]==0]
        c1 = [i for i in range(n) if y[i]==1]
        all_imp = [0.0]*nf
        for t in range(self.n_estimators):
            if t % 25 == 0 and t > 0: print(f"  ...tree {t}/{self.n_estimators}")
            if self.class_weight == 'balanced' and c1:
                half = n // 2
                bi = random.choices(c1, k=half) + random.choices(c0, k=n-half)
            else:
                bi = [random.randint(0, n-1) for _ in range(n)]
            bX = [X[i] for i in bi]; by = [y[i] for i in bi]
            tree = DecisionTree(self.max_depth, self.min_samples_split, self.max_features)
            tree.fit(bX, by)
            for fi, imp in tree.feature_importances.items():
                all_imp[fi] += imp
            self.trees.append(tree)
        total = sum(all_imp)
        self.feature_importances_ = [x/total for x in all_imp] if total > 0 else all_imp

    def predict_proba(self, X):
        return [sum(tree._predict_one(row)[1] for tree in self.trees)/len(self.trees) for row in X]

def load_dataset(filename):
    with open(filename, "r") as f:
        rows = list(csv.DictReader(f))
    fn = ["rsi_14","rsi_7","rsi_change","macd_hist",
          "is_uptrend","price_vs_sma50","price_vs_sma200","sma50_vs_sma200",
          "atr_pct","bb_width","bb_position",
          "candle_body","wick_top","wick_bot","momentum_5","momentum_10",
          "vol_change","vol_price_trend","hour_sin","hour_cos"]
    X, y = [], []
    for row in rows:
        try:
            X.append([float(row[f]) for f in fn])
            y.append(int(row["target"]))
        except: continue
    return X, y, fn

def split_stratified(X, y, test_size=0.2, seed=42):
    random.seed(seed)
    i0 = [i for i in range(len(y)) if y[i]==0]
    i1 = [i for i in range(len(y)) if y[i]==1]
    random.shuffle(i0); random.shuffle(i1)
    t0 = int(len(i0)*test_size); t1 = int(len(i1)*test_size)
    ti = i0[:t0]+i1[:t1]; tri = i0[t0:]+i1[t1:]
    return ([X[i] for i in tri],[X[i] for i in ti],[y[i] for i in tri],[y[i] for i in ti])

def train_and_evaluate(csv_file):
    symbol = csv_file.split("_")[0].upper()
    print(f"\n{'='*60}\n  TRAINING AI MODEL: {symbol}\n{'='*60}")
    X, y, fn = load_dataset(csv_file)
    n = len(y); w = sum(y)
    print(f"  Dataset: {csv_file}")
    print(f"  Total samples: {n}")
    print(f"  Wins (1): {w} | Losses (0): {n-w}")
    print(f"  Win rate: {w/n*100:.1f}%")
    print(f"  Features: {len(fn)}")
    Xtr, Xte, ytr, yte = split_stratified(X, y)
    print(f"\n  Train: {len(ytr)} ({sum(ytr)} wins) | Test: {len(yte)} ({sum(yte)} wins)")
    model = RandomForest(n_estimators=150, max_depth=8, min_samples_split=10,
                         max_features=4, random_state=42, class_weight='balanced')
    print(f"\n  Training Random Forest (150 trees, max_depth=8)...")
    t0 = time.time(); model.fit(Xtr, ytr); t1 = time.time()
    print(f"  Done in {t1-t0:.1f}s")
    ypr = model.predict_proba(Xte)
    print(f"\n{'='*60}\n  THRESHOLD ANALYSIS\n{'='*60}")
    print(f"  {'Threshold':>10} | {'Signals':>8} | {'Wins':>5} | {'Win%':>6} | {'Exp PnL':>8}")
    print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*5}-+-{'-'*6}-+-{'-'*8}")
    bt, bp = 0.5, -999
    for th in [0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85]:
        pr = [1 if p>=th else 0 for p in ypr]
        s = sum(pr); wins = sum(1 for i in range(len(yte)) if pr[i]==1 and yte[i]==1)
        if s > 0:
            wr = wins/s*100; pnl = (wr/100*2.5)-((100-wr)/100*2.5)-0.1
            print(f"  {th*100:>9.0f}% | {s:>8} | {wins:>5} | {wr:>5.1f}% | {pnl:>+7.2f}%")
            if pnl > bp and s >= 5: bp = pnl; bt = th
        else:
            print(f"  {th*100:>9.0f}% | {s:>8} | {wins:>5} |   N/A |     N/A")
    print(f"\n  Best: {bt*100:.0f}% threshold (Exp PnL: {bp:+.2f}%)")
    print(f"\n{'='*60}\n  FEATURE IMPORTANCE\n{'='*60}")
    imp = model.feature_importances_
    si = sorted(range(len(imp)), key=lambda i: imp[i], reverse=True)
    for idx in si:
        bar = "#" * int(imp[idx]*50)
        print(f"  {fn[idx]:20s} {imp[idx]:.4f} {bar}")
    mf = f"{symbol.lower()}_model.pkl"
    with open(mf, "wb") as f:
        pickle.dump({'trees': [t.tree for t in model.trees], 'features': fn, 'threshold': bt}, f)
    print(f"\n✅ Model saved to {mf}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 train_model.py <dataset.csv>")
        sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"Error: {sys.argv[1]} not found"); sys.exit(1)
    train_and_evaluate(sys.argv[1])
