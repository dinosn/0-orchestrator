package vdisk

import (
	"github.com/zero-os/0-orchestrator/api/validators"
	"gopkg.in/validator.v2"
)

type VdiskCreate struct {
	ID                   string                   `yaml:"-" json:"id" validate:"nonzero,servicename"`
	Blocksize            int                      `yaml:"blocksize" json:"blocksize" validate:"nonzero"`
	ReadOnly             bool                     `yaml:"readOnly" json:"readOnly,omitempty"`
	Size                 int                      `yaml:"size" json:"size" validate:"nonzero,max=2048"`
	Storagecluster       string                   `yaml:"storagecluster" json:"storagecluster" validate:"nonzero"`
	Templatevdisk        string                   `yaml:"templatevdisk" json:"templatevdisk,omitempty"`
	TlogStoragecluster   string                   `yaml:"tlogStoragecluster" json:"tlogStoragecluster,omitempty"`
	BackupStoragecluster string                   `yaml:"backupStoragecluster" json:"backupStoragecluster,omitempty"`
	Vdisktype            EnumVdiskCreateVdisktype `yaml:"type" json:"type" validate:"nonzero"`
}

func (s VdiskCreate) Validate() error {
	typeEnums := map[interface{}]struct{}{
		EnumVdiskCreateVdisktypeboot:  struct{}{},
		EnumVdiskCreateVdisktypedb:    struct{}{},
		EnumVdiskCreateVdisktypecache: struct{}{},
		EnumVdiskCreateVdisktypetmp:   struct{}{},
	}

	if err := validators.ValidateEnum("Vdisktype", s.Vdisktype, typeEnums); err != nil {
		return err
	}

	if err := validators.ValidateVdisk(string(s.Vdisktype), s.TlogStoragecluster, s.Templatevdisk, s.Blocksize, s.BackupStoragecluster); err != nil {
		return err
	}

	return validator.Validate(s)
}
