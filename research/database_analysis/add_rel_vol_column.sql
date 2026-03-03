-- Adds precomputed relative volume column for backtesting speedups
ALTER TABLE public.stock_candles_1m
ADD COLUMN IF NOT EXISTS rel_vol_30d DOUBLE PRECISION;
