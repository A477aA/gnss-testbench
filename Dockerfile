# Воспроизводимое окружение стенда: docker run --rm gnss-testbench run scenarios/open_sky_rtk.toml
# Реальный приёмник: docker run --rm --device /dev/ttyUSB0 gnss-testbench capture --port /dev/ttyUSB0 -o /data/log.nmea
FROM python:3.12-slim

RUN useradd --create-home --groups dialout bench
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY scenarios ./scenarios
COPY criteria ./criteria

USER bench
ENTRYPOINT ["gnss-testbench"]
CMD ["--help"]
