@0xc75c2e3ade4b6c71;

struct Schema {
    node @0 :Text; # Pointer to the parent service
    port @1 :UInt32 = 8086; # port to connect to influxdb
    databases @2: List(Text); # database to dump statistics to
    container @3 :Text; # Container spawned by this service
    status @4 :Status;

    enum Status{
        halted @0;
        running @1;
    }
}
