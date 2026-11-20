"""Camada 2 (ciclos), contrato A' (i_last junto do ultimo pixel; sem i_flush)."""
import random


class ContractError(Exception):
    pass


MUTANTS = (
    "lat_plus1", "lat_minus1", "cnt_no_valid", "use_i_valid", "mask_late",
    "warm_early", "warm_late", "flush_short", "flush_long", "no_restart",
    "no_mask_left", "no_mask_right", "no_mask_top", "no_mask_bottom",
    "last_no_flush",
)
CONTRACT_MUTANTS = ("no_last_check", "no_busy_check", "last_without_valid_ok")


class LineBufferContract:
    def __init__(self, w):
        self.w = w
        self.hist = []
        self.valid = 0
        self.curr = self.line1 = self.line2 = 0

    def step(self, i_valid, i_pixel):
        if i_valid:
            g = len(self.hist)
            self.hist.append(i_pixel)
            self.curr = i_pixel
            self.line1 = self.hist[g - self.w] if g >= self.w else 0
            self.line2 = self.hist[g - 2 * self.w] if g >= 2 * self.w else 0
        self.valid = 1 if i_valid else 0


class WindowStreamCycleModel:
    LATENCY = 2

    def __init__(self, w, h, mutant=None, seed=0):
        if w < 2 or h < 1:
            raise ValueError("W>=2, H>=1")
        if mutant is not None and mutant not in MUTANTS + CONTRACT_MUTANTS:
            raise ValueError(f"mutante desconhecido: {mutant}")
        self.w, self.h, self.mutant = w, h, mutant
        self.flush_len = {"flush_short": w, "flush_long": w + 2}.get(mutant, w + 1)
        self.thr = {"warm_early": w, "warm_late": w + 2}.get(mutant, w + 1)
        self.rng = random.Random(seed)
        self.lb = LineBufferContract(w)
        self.lb_last = 0
        self.sr = [(0, 0, 0)] * 3
        self.n_cnt = self.cc = self.rr = 0
        self.out_valid = self.out_cc = self.out_rr = 0
        self.busy = self.flush_cnt = self.tot_in = 0
        self.d_valid, self.d_window = 0, None

    def ready(self):
        return 0 if self.busy else 1

    def _window(self, sr, cc, rr):
        w, h, m = self.w, self.h, self.mutant
        win = [[sr[c][r] for c in range(3)] for r in range(3)]
        if cc == 0 and m != "no_mask_left":
            for r in range(3): win[r][0] = 0
        if cc == w - 1 and m != "no_mask_right":
            for r in range(3): win[r][2] = 0
        if rr == 0 and m != "no_mask_top":
            for c in range(3): win[0][c] = 0
        if rr == h - 1 and m != "no_mask_bottom":
            for c in range(3): win[2][c] = 0
        return win

    def step(self, i_valid, i_pixel, i_last=0):
        w, h, m = self.w, self.h, self.mutant
        cur_window = self._window(self.sr, self.out_cc, self.out_rr)
        base_valid = self.out_valid
        base_window = cur_window if base_valid else None
        obs = {"o_ready": self.ready(), "o_valid": base_valid,
               "o_window": base_window, "inj_valid": 0}

        busy_n, fcnt_n, tot_n = self.busy, self.flush_cnt, self.tot_in
        inj_valid, inj_pix, inj_last = 0, 0, 0
        if self.busy:
            if (i_valid or i_last) and m != "no_busy_check":
                raise ContractError("entrada durante flush (o_ready=0)")
            inj_valid = 1
            inj_pix = self.rng.randrange(256)
            inj_last = 1 if self.flush_cnt == 1 else 0
            fcnt_n = self.flush_cnt - 1
            if self.flush_cnt == 1:
                busy_n = 0
        elif i_last and not i_valid:
            if m != "last_without_valid_ok":
                raise ContractError("i_last sem i_valid")
        elif i_valid:
            inj_valid, inj_pix = 1, i_pixel
            tot_n = self.tot_in + 1
            if i_last:
                if tot_n % (w * h) != 0 and m != "no_last_check":
                    raise ContractError("i_last fora de fronteira de frame")
                if m != "last_no_flush":
                    busy_n, fcnt_n, tot_n = 1, self.flush_len, 0
        obs["inj_valid"] = inj_valid

        gate = inj_valid if m == "use_i_valid" else self.lb.valid
        thr = self.thr
        triple = (self.lb.line2, self.lb.line1, self.lb.curr)
        sr_n, n_n, cc_n, rr_n = self.sr, self.n_cnt, self.cc, self.rr
        ov_n, ocn, orn = 0, self.out_cc, self.out_rr
        if gate:
            sr_n = [self.sr[1], self.sr[2], triple]
            if self.n_cnt >= thr:
                ov_n = 1
                cc_adv = (self.cc + 1) % w
                rr_adv = (self.rr + 1) % h if self.cc == w - 1 else self.rr
                ocn, orn = (cc_adv, rr_adv) if m == "mask_late" else (self.cc, self.rr)
                cc_n, rr_n = cc_adv, rr_adv
            n_n = min(self.n_cnt + 1, thr)
            if self.lb_last and m != "no_restart":
                n_n, cc_n, rr_n = 0, 0, 0
        elif m == "cnt_no_valid":
            n_n = min(self.n_cnt + 1, thr)

        if m == "lat_minus1":
            obs["o_valid"] = ov_n
            obs["o_window"] = self._window(sr_n, ocn, orn) if ov_n else None
        if m == "lat_plus1":
            obs["o_valid"] = self.d_valid
            obs["o_window"] = self.d_window
            self.d_valid, self.d_window = base_valid, base_window

        self.sr, self.n_cnt, self.cc, self.rr = sr_n, n_n, cc_n, rr_n
        self.out_valid, self.out_cc, self.out_rr = ov_n, ocn, orn
        self.busy, self.flush_cnt, self.tot_in = busy_n, fcnt_n, tot_n
        self.lb.step(inj_valid, inj_pix)
        self.lb_last = inj_last
        return obs