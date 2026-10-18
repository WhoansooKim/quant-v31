BEGIN;

CREATE TEMP TABLE tgt(regime varchar(16), factor varchar(20), weight numeric(6,4)) ON COMMIT DROP;
INSERT INTO tgt VALUES
 ('TRENDING','technical',0.30),('TRENDING','momentum',0.12),('TRENDING','sentiment',0.10),
 ('TRENDING','flow',0.00),('TRENDING','quality',0.20),('TRENDING','value',0.00),
 ('TRENDING','macro',0.18),('TRENDING','pead',0.10),
 ('SIDEWAYS','technical',0.22),('SIDEWAYS','momentum',0.10),('SIDEWAYS','sentiment',0.10),
 ('SIDEWAYS','flow',0.00),('SIDEWAYS','quality',0.25),('SIDEWAYS','value',0.00),
 ('SIDEWAYS','macro',0.23),('SIDEWAYS','pead',0.10),
 ('HIGH_VOL','technical',0.18),('HIGH_VOL','momentum',0.10),('HIGH_VOL','sentiment',0.10),
 ('HIGH_VOL','flow',0.00),('HIGH_VOL','quality',0.25),('HIGH_VOL','value',0.00),
 ('HIGH_VOL','macro',0.27),('HIGH_VOL','pead',0.10),
 ('MIXED','technical',0.28),('MIXED','momentum',0.10),('MIXED','sentiment',0.10),
 ('MIXED','flow',0.00),('MIXED','quality',0.22),('MIXED','value',0.00),
 ('MIXED','macro',0.20),('MIXED','pead',0.10);

-- 안전장치: 32행 · 레짐별 합 1.0 이 아니면 중단
DO $$
DECLARE n int; bad int;
BEGIN
  SELECT count(*) INTO n FROM tgt;
  IF n <> 32 THEN RAISE EXCEPTION '목표 행수 % <> 32', n; END IF;
  SELECT count(*) INTO bad FROM (SELECT regime, sum(weight) s FROM tgt GROUP BY regime) q WHERE abs(s-1.0) > 0.0001;
  IF bad > 0 THEN RAISE EXCEPTION '레짐 % 개의 합이 1.0 아님', bad; END IF;
  SELECT count(*) INTO bad FROM swing_factor_weights w FULL JOIN tgt t USING (regime, factor)
    WHERE w.regime IS NULL OR t.regime IS NULL;
  IF bad > 0 THEN RAISE EXCEPTION '키 불일치 % 건', bad; END IF;
END $$;

-- 감사 기록 먼저 (되돌리기 가능하게)
INSERT INTO swing_weight_history (regime, factor, old_weight, new_weight, ic_used, reason)
SELECT w.regime, w.factor, w.weight, t.weight, NULL,
       '§22.AO-52 튜너 이전 복귀 — 무효 IC(풀링·원시수익·중복·EXIT오염) 로 움직인 auto-tune 227건 되돌림. 목표=multi_factor.REGIME_WEIGHTS(=튜너이전 + §22.AO-26 C momentum)'
FROM swing_factor_weights w JOIN tgt t USING (regime, factor)
WHERE w.weight <> t.weight;

UPDATE swing_factor_weights w
   SET weight = t.weight, updated_at = now(), updated_by = 'revert',
       reason = '§22.AO-52 튜너 이전 복귀'
  FROM tgt t
 WHERE w.regime = t.regime AND w.factor = t.factor AND w.weight <> t.weight;

COMMIT;
