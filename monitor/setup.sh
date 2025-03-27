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
                                       python -m venv venv && \
                                       venv/bin/pip install mitmproxy==11.1.3 requests==2.32.3'

  # install requests for mitm plugin
  sudo cp mitm_plugin.py /Users/mitmproxyuser/mitm_plugin.py

  # start mitmdump in simple mode for now to generate CA certificate
  sudo -u mitmproxyuser -H bash -e -c "cd /Users/mitmproxyuser && \
                                       /Users/mitmproxyuser/venv/bin/mitmdump &"

  # wait for mitmdump to start and generate CA certificate
  counter=0
  while [ ! -f /Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem ]
  do
    echo "Mac: waiting for mitmdump to generate the certificate..."
    sleep 1
    counter=$((counter+1))
    if [ $counter -gt 10 ]; then
      echo "10 seconds passed..."
      exit 1
    fi
  done

  echo "kill mitmdump..."
  # kill mitmdump, we'll start it again in transparent mode
  pid=$(sudo lsof -i -P -n 2>/dev/null | sed -En "s/Python *([0-9]*) *mitmproxyuser *.*TCP \*:8080 \(LISTEN\)/\1/p" | head -1)
  sudo kill $pid

  echo "install mitmproxy certificate as CA..."
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
  # set environment variable for AWS tools
  echo "AWS_CA_BUNDLE=/Users/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV

  # Enable IP forwarding.
  sudo sysctl -w net.inet.ip.forwarding=1
  # Configure pf with the rules and enable it
  sudo pfctl -f pf.conf
  sudo pfctl -e
  # Configure sudoers to allow mitmproxy to access pfctl.
  echo "ALL ALL=NOPASSWD: /sbin/pfctl -s state" | sudo tee -a /etc/sudoers

  # finally, start mitmdump in transparent mode
  sudo -u mitmproxyuser -H bash -e -c "cd /Users/mitmproxyuser && /Users/mitmproxyuser/venv/bin/mitmdump \
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

else

  echo "Unknown OS: $RUNNER_OS"
  exit 1

fi

echo "--all done--"
