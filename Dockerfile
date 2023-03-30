FROM python:3.11-buster

WORKDIR /usr/src/tabby

COPY poetry.lock pyproject.toml ./
RUN curl -sSL https://install.python-poetry.org | python - &&\
    poetry install

RUN apt install firefox jq -y &&\
    driver_version="v$(curl https://api.github.com/repos/mozilla/geckodriver/releases/latest | jq .name -r)" &&\
    download="$driver_version/geckodriver-$driver_version-linux64.tar.gz" &&\
    full_url="https://github.com/mozilla/geckodriver/releases/download/$download" &&\
    curl -L $full_url -o geckodriver-$driver_version.tar.gz &&\
    tar -xf geckodriver-$driver_version.tar.gz &&\
    cp ./geckodriver /usr/local/bin/geckodriver

COPY . .

CMD [ "poetry", "run", "python", "launch.py" ]
