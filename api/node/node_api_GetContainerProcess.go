package node

import (
	"encoding/json"
	"net/http"
	"strconv"

	"fmt"

	"github.com/gorilla/mux"
	client "github.com/zero-os/0-core/client/go-client"
	"github.com/zero-os/0-orchestrator/api/tools"
)

// GetContainerProcess is the handler for GET /nodes/{nodeid}/containers/{containername}/processes/{processid}
// Get process details
func (api NodeAPI) GetContainerProcess(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	conn, err := tools.GetContainerConnection(r, api)
	if err != nil {
		tools.WriteError(w, http.StatusInternalServerError, err, "Failed to establish connection to container")
		return
	}

	pId, err := strconv.ParseUint(vars["processid"], 10, 64)
	if err != nil {
		tools.WriteError(w, http.StatusBadRequest, err, "Processid should be valid positive integer")
		return
	}

	processID := client.ProcessId(pId)
	core := client.Core(conn)
	process, err := core.Process(processID)

	if err != nil {
		if err == client.NotFound {
			errmsg := fmt.Sprintf("No such process %d on container %s", pId, vars["containername"])
			tools.WriteError(w, http.StatusNotFound, err, errmsg)

		} else {
			errmsg := fmt.Sprintf("Error getting process %s info on container", processID)
			tools.WriteError(w, http.StatusInternalServerError, err, errmsg)
		}
		return
	}

	cpu := CPUStats{
		GuestNice: process.Cpu.GuestNice,
		Idle:      process.Cpu.Idle,
		IoWait:    process.Cpu.IoWait,
		Irq:       process.Cpu.Irq,
		Nice:      process.Cpu.Nice,
		SoftIrq:   process.Cpu.SoftIrq,
		Steal:     process.Cpu.Steal,
		Stolen:    process.Cpu.Stolen,
		System:    process.Cpu.System,
		User:      process.Cpu.User,
	}

	respBody := Process{
		Cmdline: process.Command,
		Cpu:     cpu,
		Pid:     pId,
		Rss:     process.RSS,
		Swap:    process.Swap,
		Vms:     process.VMS,
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(&respBody)
}
