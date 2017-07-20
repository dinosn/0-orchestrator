@0xf6773e7b7181183f;

struct Schema {
    backendControllerUrl @0 :Text;
    vdiskControllerUrl @1 :Text;
    socketPath @2 :Text; # uri of the unix socket path
    container @3 :Text; # parent
    status @4: Status;

    enum Status{
        halted @0;
        running @1;
        halting @2;
    }

}
