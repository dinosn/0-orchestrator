#!/bin/bash

point=$1
if [ "$TRAVIS_EVENT_TYPE" == "cron" ] || [ "$TRAVIS_EVENT_TYPE" == "api" ]
 then
   if [ "$point" == "before" ]
    then
      pip3 install -r tests/Grid_API_Testing/requirements.txt
      pip3 install git+https://github.com/gigforks/packet-python.git
      bash tests/Grid_API_Testing/install_env.sh 1.1.0-alpha-5 $ZT_NET_ID $ZT_TOKEN
      cd tests/Grid_API_Testing; python3 orch_packet_machines.py create $PACKET_TOKEN $ZT_NET_ID $ITSYOUONLINE_ORG 1.1.0-alpha-5
   elif [ "$point" == "run" ]
    then
      echo "sleeping 333"
      sleep 333
      echo "Running tests .."
      cd tests/Grid_API_Testing/
      export PYTHONPATH='./'
      nosetests-3.4 -v -s api_testing/testcases --tc-file=api_testing/config.ini --tc=main.zerotier_token:$ZT_TOKEN --tc=main.client_id:$ITSYOUONLINE_CL_ID --tc=main.client_secret:$ITSYOUONLINE_CL_SECRET --tc=main.organization:$ITSYOUONLINE_ORG
   elif [ "$point" == "after" ]
    then
      cd tests/Grid_API_Testing/
      python3 orch_packet_machines.py delete $PACKET_TOKEN
   fi
 else
   echo "Not a cron job" 
fi

