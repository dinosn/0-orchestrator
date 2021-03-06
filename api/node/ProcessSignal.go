package node

import (
	"gopkg.in/validator.v2"
)

type ProcessSignal struct {
	Signal int8 `json:"signal" validate:"min=1,nonzero"`
}

func (s ProcessSignal) Validate() error {

	return validator.Validate(s)
}
