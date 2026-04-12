@echo off
echo === Aspire Dashboard (OpenTelemetry) ===
echo.
echo Browser UI : http://localhost:18888
echo OTLP gRPC  : http://localhost:4317
echo.
echo Set in backend\.env: OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:14317
echo.
docker compose -f docker-compose.aspire.yml up esg-advisor
pause
