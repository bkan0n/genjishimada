-- Ensure playtest seed maps have non-null difficulty values

UPDATE core.maps
SET difficulty = 'Medium'
WHERE code IN ('PTEST1', 'PTEST2', 'PTEST3');
