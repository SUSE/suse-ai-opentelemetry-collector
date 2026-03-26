package topologyexporter

import (
	"errors"
	"time"

	"go.opentelemetry.io/collector/config/configtls"
)

type Config struct {
	TLS           configtls.ClientConfig `mapstructure:"tls"`
	Endpoint      string                 `mapstructure:"endpoint"`
	ServiceToken  string                 `mapstructure:"service_token"`
	InstanceType  string                 `mapstructure:"instance_type"`
	InstanceURL   string                 `mapstructure:"instance_url"`
	FlushInterval time.Duration          `mapstructure:"flush_interval"`
	Namespace     string                 `mapstructure:"namespace"`
}

func createDefaultConfig() *Config {
	return &Config{
		InstanceType:  "suse-ai",
		InstanceURL:   "local",
		FlushInterval: 60 * time.Second,
	}
}

func (cfg *Config) Validate() error {
	if cfg.Endpoint == "" {
		return errors.New("endpoint is required")
	}
	if cfg.ServiceToken == "" {
		return errors.New("service_token is required")
	}
	if cfg.FlushInterval < 10*time.Second {
		return errors.New("flush_interval must be >= 10s")
	}
	return nil
}
