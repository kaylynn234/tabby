FROM python:3.11-buster

WORKDIR /usr/src/tabby

RUN apt update &&\
    apt install firefox-esr jq -y &&\
    driver_version="v$(curl https://api.github.com/repos/mozilla/geckodriver/releases/latest | jq .name -r)" &&\
    download="$driver_version/geckodriver-$driver_version-linux64.tar.gz" &&\
    full_url="https://github.com/mozilla/geckodriver/releases/download/$download" &&\
    curl -L $full_url -o geckodriver-$driver_version.tar.gz &&\
    tar -xf geckodriver-$driver_version.tar.gz &&\
    cp ./geckodriver /usr/local/bin/geckodriver &&\
    chmod +x /usr/local/bin/geckodriver

COPY poetry.lock pyproject.toml ./
RUN curl -sSL https://install.python-poetry.org | python - &&\
    export PATH="/root/.local/bin:$PATH" &&\
    poetry install

CMD [ "/root/.local/bin/poetry", "run", "python", "launch.py" ]
