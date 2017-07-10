@0x9b086fb7291fcce5; 

struct Schema {
    node @0 :Text; # Pointer to the parent service
    ip @1 :Text; # ip to connect to influxdb
    port @2 :UInt32 = 8086; # port to connect to influxdb
    db @3: Text = "statistics"; # database to dump statistics to
    retention @4 :Text = "5d"; # influxdb retention policy
    container @5 :Text; # Container spawned by this service
    status @6 :Status;

    enum Status{
        halted @0;
        running @1;
    }
}
