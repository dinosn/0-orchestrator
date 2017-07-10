@0xfa844e8aee1ee5f2; 

struct Schema {
    node @0 :Text; # Pointer to the parent service
    influxdb @1 :List(Text); # influx db to connect to
    port @2 : UInt32 = 3000; # port
    container @3 : Text; # Container spawned by this service
    status @4 :Status;

    enum Status{
        halted @0;
        running @1;
    }
}
