@0xc43b00ba0d693602; 

struct Schema {
    node @0 :Text; # Pointer to the parent service
    port @1 :UInt32 = 8086; # port to connect to influxdb
    influxdb @2 :Text; # Influxdb spawned by this service
    status @3 :Status;
    grafana @4 :Text;

    enum Status{
        halted @0;
        running @1;
    }
}
