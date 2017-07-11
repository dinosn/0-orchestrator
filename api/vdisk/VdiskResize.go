package vdisk

import (
	"gopkg.in/validator.v2"
)

type VdiskResize struct {
	NewSize int `yaml:"newSize" json:"newSize" validate:"nonzero,max=2048"`
}

func (s VdiskResize) Validate() error {

	return validator.Validate(s)
}
