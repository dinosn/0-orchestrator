package node

import (
	"encoding/json"
	"net/http"
	"syscall"

	"strconv"

	"fmt"

	"github.com/gorilla/mux"
	client "github.com/zero-os/0-core/client/go-client"
	"github.com/zero-os/0-orchestrator/api/tools"
)

// SendSignalProcess is the handler for POST /nodes/{nodeid}/containers/{containername}/processes/{processid}
// Send signal to the process
func (api NodeAPI) SendSignalProcess(w http.ResponseWriter, r *http.Request) {
	var reqBody ProcessSignal

	// decode request
	if err := json.NewDecoder(r.Body).Decode(&reqBody); err != nil {
		tools.WriteError(w, http.StatusBadRequest, err, "Error decoding request body")
		return
	}

	// validate request
	if err := reqBody.Validate(); err != nil {
		tools.WriteError(w, http.StatusBadRequest, err, "")
		return
	}

	vars := mux.Vars(r)
	pId, err := strconv.ParseUint(vars["processid"], 10, 64)

	if err != nil {
		tools.WriteError(w, http.StatusInternalServerError, err, "Error casting process id into an intiger")
		return
	}

	processId := client.ProcessId(pId)

	// Get container connection
	cl, err := tools.GetContainerConnection(r, api)
	if err != nil {
		tools.WriteError(w, http.StatusInternalServerError, err, "Failed to establish connection to container")
		return
	}

	// Send signal to the container process
	core := client.Core(cl)
	if err := core.KillProcess(processId, syscall.Signal(reqBody.Signal)); err != nil {
		errmsg := fmt.Sprintf("Error sending signal %s to process %s", reqBody.Signal, processId)
		tools.WriteError(w, http.StatusInternalServerError, err, errmsg)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}
