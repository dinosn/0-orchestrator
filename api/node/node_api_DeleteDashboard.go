package node

import (
	"net/http"

	"fmt"

	"github.com/gorilla/mux"
	"github.com/zero-os/0-orchestrator/api/tools"
)

// DeleteDashboard is the handler for DELETE /graph/{graphid}/dashboard/{dashboardid}
// Remove dashboard
func (api NodeAPI) DeleteDashboard(w http.ResponseWriter, r *http.Request) {
	aysClient := tools.GetAysConnection(r, api)
	vars := mux.Vars(r)
	dashboard := vars["dashboardid"]

	exists, err := aysClient.ServiceExists("dashboard", dashboard, api.AysRepo)

	if err != nil {
		tools.WriteError(w, http.StatusInternalServerError, err, "Failed to check for the dashboard")
		return
	}

	if !exists {
		err = fmt.Errorf("Dashboard %s doesn't exist", dashboard)
		tools.WriteError(w, http.StatusNotFound, err, err.Error())
		return
	}

	// execute the delete action of the snapshot
	blueprint := map[string]interface{}{
		"actions": []tools.ActionBlock{{
			Action:  "delete",
			Actor:   "dashboard",
			Service: dashboard,
			Force:   true,
		}},
	}

	run, err := aysClient.ExecuteBlueprint(api.AysRepo, "dashboard", dashboard, "delete", blueprint)
	errmsg := "Error executing blueprint for dashboard deletion "
	if !tools.HandleExecuteBlueprintResponse(err, w, errmsg) {
		return
	}

	// Wait for the delete job to be finshed before we delete the service
	if _, err = aysClient.WaitRunDone(run.Key, api.AysRepo); err != nil {
		httpErr, ok := err.(tools.HTTPError)
		if ok {
			tools.WriteError(w, httpErr.Resp.StatusCode, httpErr, "")
		} else {
			tools.WriteError(w, http.StatusInternalServerError, err, "Error running blueprint for dashboard deletion")
		}
		return
	}

	_, err = aysClient.Ays.DeleteServiceByName(dashboard, "dashboard", api.AysRepo, nil, nil)

	if err != nil {
		errmsg := fmt.Sprintf("Error in deleting dashboard %s ", dashboard)
		tools.WriteError(w, http.StatusInternalServerError, err, errmsg)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
