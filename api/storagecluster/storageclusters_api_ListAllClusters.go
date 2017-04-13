package storagecluster

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/g8os/grid/api/tools"
)

// ListAllClusters is the handler for GET /storageclusters
// List all running clusters
func (api StorageclustersAPI) ListAllClusters(w http.ResponseWriter, r *http.Request) {
	respBody := []string{}
	type data struct {
		Label string `json:"label"`
	}
	query := map[string]interface{}{
		"fields": "label",
	}
	services, res, err := api.AysAPI.Ays.ListServicesByRole("storage_cluster", api.AysRepo, nil, query)
	if err != nil {
		tools.WriteError(w, http.StatusInternalServerError, err)
		return
	}
	if res.StatusCode != http.StatusOK {
		w.WriteHeader(res.StatusCode)
		return
	}

	for _, service := range services {
		fmt.Print("\nname is  ", service.Name)
		fmt.Print("\n\ndata is  ", service.Data)
		Data := data{}
		if err := json.Unmarshal(service.Data, &Data); err != nil {
			tools.WriteError(w, http.StatusInternalServerError, err)
			return
		}
		fmt.Print("\n\nlabel is ", Data, "\n\n")
		respBody = append(respBody, Data.Label)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(&respBody)
}
