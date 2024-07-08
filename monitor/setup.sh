#!/bin/bash

set -e

# build the filter regex for mitmproxy --allow-hosts
filter='\b('
first=true
IFS=',' read -ra args <<< "$@"
for arg in "${args[@]}"; do
  if [ "$first" = true ] ; then
    first=false
  else
    filter+='|'
  fi
  filter+=${arg//./\\.}
done
filter+=')(:\d+)?|$'

if [ "$RUNNER_OS" = "macOS" ]; then

  echo "runner ALL=(ALL) NOPASSWD: ALL" | sudo tee -a /etc/sudoers
  sudo sysadminctl -addUser mitmproxyuser -admin

  sudo -u mitmproxyuser -H bash -e -c 'cd /Users/mitmproxyuser && \
                                       git clone -b main https://github.com/mitmproxy/mitmproxy.git && \
                                       cd mitmproxy && \
                                       git checkout 5353df5f1eeaf5fc36d9b5f7024199c888aed116 && \
                                       python -m venv venv && \
                                       venv/bin/pip install -e ".[dev]" '

  # install requests for mitm plugin
  sudo cp mitm_plugin.py /Users/mitmproxyuser/mitm_plugin.py

  # start mitmdump in simple mode for now to generate CA certificate
  sudo -u mitmproxyuser -H bash -e -c "cd /Users/mitmproxyuser && \
                                       /Users/mitmproxyuser/mitmproxy/venv/bin/mitmdump &"

  # wait for mitmdump to start and generate CA certificate
  counter=0
  while [ ! -f /Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem ]
  do
    echo "waiting for mitmdump to generate the certificate..."
    sleep 1
    counter=$((counter+1))
    if [ $counter -gt 10 ]; then
      exit 1
    fi
  done

  # kill mitmdump, we'll start it again in transparent mode
  pid=$(sudo lsof -i -P -n 2>/dev/null | sed -En "s/Python *([0-9]*) *mitmproxyuser *.*TCP \*:8080 \(LISTEN\)/\1/p" | head -1)
  sudo kill $pid

  # install mitmproxy certificate as CA
  # disable any GUI prompts for certificate installation
  sudo security authorizationdb write com.apple.trust-settings.admin allow
  # the command itself may run https requests, this is why we didn't setup transparent proxy yet
  # TODO: check if -r trustRoot is needed
  sudo security add-trusted-cert -d -p ssl -p basic -k /Library/Keychains/System.keychain /Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem
  # sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem
  # curl doesn't use the system keychain, so we need to add the certificate to the openssl keychain
  sudo cat /Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem >> `openssl version -d | awk '{ gsub(/"/, "", $2); print $2 }'`/cert.pem
  # set environment variable for NodeJS to use the certificate
  echo "NODE_EXTRA_CA_CERTS=/Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
  # set environment variable for the Python requests library to use the certificate
  echo "REQUESTS_CA_BUNDLE=/Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
  # set environment variable for the Elixir Hex package manager to use the certificate
  echo "HEX_CACERTS_PATH=/Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV

  # Enable IP forwarding.
  sudo sysctl -w net.inet.ip.forwarding=1
  # Configure pf with the rules and enable it
  sudo pfctl -f pf.conf
  sudo pfctl -e
  # Configure sudoers to allow mitmproxy to access pfctl.
  echo "ALL ALL=NOPASSWD: /sbin/pfctl -s state" | sudo tee -a /etc/sudoers

  # finally, start mitmdump in transparent mode
  sudo -u mitmproxyuser -H bash -e -c "cd /Users/mitmproxyuser && /Users/mitmproxyuser/mitmproxy/venv/bin/mitmdump \
          --mode transparent \
          --showhost \
          --allow-hosts '$filter' \
          -q \
          `#--set termlog_verbosity=debug` \
          `#--set proxy_debug=true` \
          -s /Users/mitmproxyuser/mitm_plugin.py \
          --set output='/Users/mitmproxyuser/out.txt' \
          --set token='$INPUT_TOKEN' \
          --set hosts=$@ \
          --set debug='$RUNNER_DEBUG' \
          --set ACTIONS_ID_TOKEN_REQUEST_URL='$ACTIONS_ID_TOKEN_REQUEST_URL' \
          --set ACTIONS_ID_TOKEN_REQUEST_TOKEN='$ACTIONS_ID_TOKEN_REQUEST_TOKEN' \
          --set GITHUB_REPOSITORY_ID='$GITHUB_REPOSITORY_ID' \
          --set GITHUB_REPOSITORY='$GITHUB_REPOSITORY' \
          --set GITHUB_API_URL='$GITHUB_API_URL' \
          &"
          # >>/Users/mitmproxyuser/out.txt 2>&1

  # wait for mitmdump to start
  counter=0
  while [ ! $(sudo lsof -i -P -n 2>/dev/null | sed -En "s/Python *([0-9]*) *mitmproxyuser *.*TCP \*:8080 \(LISTEN\)/\1/p" | head -1) ]
  do
    echo "waiting for mitmdump to start..."
    sleep 1
    counter=$((counter+1))
    if [ $counter -gt 10 ]; then
      exit 1
    fi
  done

  echo "pid is $(sudo lsof -i -P -n 2>/dev/null | sed -En "s/Python *([0-9]*) *mitmproxyuser *.*/\1/p" | head -1)"

elif [ "$RUNNER_OS" = "Linux" ]; then

  # install python 3.10, otherwise ubuntu 20.04 installs 3.8 and we won't get the latest mitmproxy with important bug fixes
  sudo add-apt-repository ppa:deadsnakes/ppa -y
  sudo apt install -y python3.10-venv

  # create mitmproxyuser, otherwise proxy won't intercept local trafic from the same user
  sudo useradd --create-home mitmproxyuser
  sudo passwd -d mitmproxyuser

  # install mitmproxy
  sudo -u mitmproxyuser -H bash -e -c 'cd ~ && \
                                       git clone -b main https://github.com/mitmproxy/mitmproxy.git && \
                                       cd mitmproxy && \
                                       git checkout 5353df5f1eeaf5fc36d9b5f7024199c888aed116 && \
                                       python3.10 -m venv venv && \
                                       venv/bin/pip install -e ".[dev]" '

  sudo cp mitm_plugin.py /home/mitmproxyuser/mitm_plugin.py
  sudo -u mitmproxyuser -H bash -e -c "cd /home/mitmproxyuser && \
      /home/mitmproxyuser/mitmproxy/venv/bin/mitmdump \
          --mode transparent \
          --showhost \
          --allow-hosts '$filter' \
          -q \
          `#--set termlog_verbosity=debug` \
          `#--set proxy_debug=true` \
          -s /home/mitmproxyuser/mitm_plugin.py \
          --set output='/home/mitmproxyuser/out.txt' \
          --set token='$INPUT_TOKEN' \
          --set hosts=$@ \
          --set debug='$RUNNER_DEBUG' \
          --set ACTIONS_ID_TOKEN_REQUEST_URL='$ACTIONS_ID_TOKEN_REQUEST_URL' \
          --set ACTIONS_ID_TOKEN_REQUEST_TOKEN='$ACTIONS_ID_TOKEN_REQUEST_TOKEN' \
          --set GITHUB_REPOSITORY_ID='$GITHUB_REPOSITORY_ID' \
          --set GITHUB_REPOSITORY='$GITHUB_REPOSITORY' \
          --set GITHUB_API_URL='$GITHUB_API_URL' \
          &"
          # >>/home/mitmproxyuser/out.txt 2>&1

  # wait for mitmdump to start and generate CA certificate
  counter=0
  while [ ! -f /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem ]
  do
    echo "waiting for mitmdump to generate the certificate..."
    sleep 1
    counter=$((counter+1))
    if [ $counter -gt 10 ]; then
      exit 1
    fi
  done

  # install mitmproxy certificate as CA
  sudo mkdir /usr/local/share/ca-certificates/extra
  sudo openssl x509 -in /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem -inform PEM -out ~/mitmproxy-ca-cert.crt
  sudo cp ~/mitmproxy-ca-cert.crt /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt
  sudo dpkg-reconfigure -p critical ca-certificates
  sudo update-ca-certificates
  # set environment variable for NodeJS to use the certificate
  echo "NODE_EXTRA_CA_CERTS=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
  # set environment variable for the Python requests library to use the certificate
  echo "REQUESTS_CA_BUNDLE=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
  # set environment variable for the Elixir Hex package manager to use the certificate
  echo "HEX_CACERTS_PATH=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV

  # setup global redirection
  sudo sysctl -w net.ipv4.ip_forward=1
  sudo sysctl -w net.ipv6.conf.all.forwarding=1
  sudo sysctl -w net.ipv4.conf.all.send_redirects=0
  sudo iptables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 80 -j REDIRECT --to-port 8080
  sudo iptables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 443 -j REDIRECT --to-port 8080
  sudo ip6tables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 80 -j REDIRECT --to-port 8080
  sudo ip6tables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 443 -j REDIRECT --to-port 8080

elif [ "$RUNNER_OS" = "Windows" ]; then

  echo "Windows is not supported yet"
  exit 1

else

  echo "Unknown OS: $RUNNER_OS"
  exit 1

fi

echo "--all done--"
