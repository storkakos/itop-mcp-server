# TEST ONLY. Python client that plays the browser and the admin for the test stack.
FROM python:3.13.18-slim
RUN pip install -q --root-user-action=ignore --disable-pip-version-check \
      requests==2.32.5 beautifulsoup4==4.13.5 lxml==6.0.2 PyMySQL==1.1.2
WORKDIR /w
COPY *.py /w/
COPY groups/ /w/groups/
