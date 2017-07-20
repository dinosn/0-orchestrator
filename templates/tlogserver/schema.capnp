@0xa2d7ef76f23ce9a6;

struct Schema {
    container @0 :Text; # parent
    bind @1 :Text; # parent
    status @2: Status;

    enum Status{
        halted @0;
        running @1;
        halting @2;
    }

}
