@0x935023b5e21bf041;

struct Schema {
    homeDir @0 :Text;
    bind @1: Text; # listen bind address.

    master @3 :Text;
    # name of other ardb service that needs to be used as master
    # if this is filled, this instance will behave as a slave

    container @4 :Text; # pointer to the parent service
}
