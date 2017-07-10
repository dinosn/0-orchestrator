package tools

import (
	"crypto/ecdsa"
	"fmt"
	"net/http"
	"strings"

	"encoding/json"
	log "github.com/Sirupsen/logrus"
	jwt "github.com/dgrijalva/jwt-go"
	"time"
)

// Oauth2itsyouonlineMiddleware is oauth2 middleware for itsyouonline
type Oauth2itsyouonlineMiddleware struct {
	describedBy string
	field       string
	org         string
}

type JWTClaim struct {
	scopes []string
	azp    string
}

var JWTPublicKey *ecdsa.PublicKey

const (
	oauth2ServerPublicKey = `\
-----BEGIN PUBLIC KEY-----
MHYwEAYHKoZIzj0CAQYFK4EEACIDYgAES5X8XrfKdx9gYayFITc89wad4usrk0n2
7MjiGYvqalizeSWTHEpnd7oea9IQ8T5oJjMVH5cc0H5tFSKilFFeh//wngxIyny6
6+Vq5t5B0V0Ehy01+2ceEon2Y0XDkIKv
-----END PUBLIC KEY-----`

	maxJWTDuration int64 = 3600 //1 hour
)

func init() {
	var err error

	if len(oauth2ServerPublicKey) == 0 {
		return
	}
	JWTPublicKey, err = jwt.ParseECPublicKeyFromPEM([]byte(oauth2ServerPublicKey))
	if err != nil {
		log.Fatalf("failed to parse pub key:%v", err)
	}

}

// NewOauth2itsyouonlineMiddlewarecreate new Oauth2itsyouonlineMiddleware struct
func NewOauth2itsyouonlineMiddleware(org string) *Oauth2itsyouonlineMiddleware {

	om := Oauth2itsyouonlineMiddleware{
		org: org,
	}

	om.describedBy = "headers"
	om.field = "Authorization"

	return &om
}

// CheckScopes checks whether user has needed scopes
func (om *Oauth2itsyouonlineMiddleware) CheckScopes(claims jwt.MapClaims) bool {
	requiredscope := fmt.Sprintf("user:memberof:%s", om.org)
	for _, claimedscope := range claims["scope"].([]interface{}) {
		if claimedscope == requiredscope {
			return true
		}
	}
	return false
}

// Handler return HTTP handler representation of this middleware
func (om *Oauth2itsyouonlineMiddleware) Handler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var accessToken string
		var err error
		if om.org == "" {
			next.ServeHTTP(w, r)
			return
		}

		// access token checking
		if om.describedBy == "queryParameters" {
			accessToken = r.URL.Query().Get(om.field)
		} else if om.describedBy == "headers" {
			accessToken = r.Header.Get(om.field)
		}
		if accessToken == "" {
			w.WriteHeader(401)
			return
		}

		var claim jwt.MapClaims
		if len(oauth2ServerPublicKey) > 0 {
			claim, err = om.getJWTClaim(accessToken)
			if err != nil {
				validationerror, ok := err.(*jwt.ValidationError)
				if ok {
					log.Error(validationerror)
					if validationerror.Errors&jwt.ValidationErrorExpired == jwt.ValidationErrorExpired {
						w.WriteHeader(440)
					} else {
						w.WriteHeader(403)
					}
				} else {
					log.Error(err)
					w.WriteHeader(403)
				}
				return
			}
		}

		// check scopes
		if !om.CheckScopes(claim) && om.org != claim["azp"] {
			w.WriteHeader(403)
			return
		}

		next.ServeHTTP(w, r)
	})
}

//validate that the expiration date of a token is not too long
func (om *Oauth2itsyouonlineMiddleware) validExpiration(claims jwt.MapClaims) error {
	now := time.Now().Unix()
	if !claims.VerifyExpiresAt(now, true) {
		//we call the verify expires at with required=True to make sure that
		//the exp flag is set.
		return fmt.Errorf("JWT token expired")
	}

	exp := claims["exp"]

	var ts int64
	switch exp := exp.(type) {
	case float64:
		ts = int64(exp)
	case json.Number:
		ts, _ = exp.Int64()
	}

	if ts-now > maxJWTDuration {
		return fmt.Errorf("JWT token expiration exceeds max allowed expiration of %v", time.Duration(maxJWTDuration)*time.Second)
	}

	return nil
}

// gets a valid jwt claims, otherwise return an error
func (om *Oauth2itsyouonlineMiddleware) getJWTClaim(tokenStr string) (jwt.MapClaims, error) {
	jwtStr := strings.TrimSpace(strings.TrimPrefix(tokenStr, "Bearer"))
	token, err := jwt.Parse(jwtStr, func(token *jwt.Token) (interface{}, error) {
		if token.Method != jwt.SigningMethodES384 {
			return nil, fmt.Errorf("Unexpected signing method: %v", token.Header["alg"])
		}
		return JWTPublicKey, nil
	})

	if err != nil {
		return nil, err
	}

	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return nil, fmt.Errorf("Invalid claims")
	}

	if err := om.validExpiration(claims); err != nil {
		return nil, err
	}

	return claims, nil
}
