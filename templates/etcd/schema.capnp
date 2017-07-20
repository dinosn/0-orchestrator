@0x829c4d8a68b27476;

struct Schema {
    peers @0: List(Text); # list of peers urls in the cluster
    container @1 :Text; # pointer to the parent service
    serverBind @2 :Text; # server listen address.
    clientBind @3 :Text; # client bind address.
    status @4: Status;

    enum Status{
        halted @0;
        running @1;
        halting @2;
    }
}
