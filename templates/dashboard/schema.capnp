@0xe561cafba88022ad;

struct Schema {
    grafana @0 :Text; # Pointer to the parent service
    dashboard @1 :Text; # A json string describing the dashboard
    slug @2 : Text; # the slug used for the api (should't be set manually)
    status @3 :Status;

    enum Status{
        halted @0;
        running @1;
    }
}
