-- Mark seed quality ratings as verified for minimum quality filtering

UPDATE maps.ratings
SET verified = TRUE
WHERE verified IS DISTINCT FROM TRUE;
