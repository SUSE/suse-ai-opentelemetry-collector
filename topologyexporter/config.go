package topologyexporter

import (
	"errors"
	"time"

	"go.opentelemetry.io/collector/config/configtls"
)

type Config struct {
	TLS           configtls.ClientConfig `mapstructure:"tls"`
	Endpoint      string                 `mapstructure:"endpoint"`
	APIKey        string                 `mapstructure:"api_key"`
	FlushInterval time.Duration          `mapstructure:"flush_interval"`
	Retention     time.Duration          `mapstructure:"retention"`
	Namespace     string                 `mapstructure:"namespace"`
	// ClusterName is attached to every product component as a k8s.cluster.name
	// metadata label. It is intentionally NOT part of the component URN, so the
	// same product observed on different clusters still aggregates into a single
	// component (matching the OpenTelemetry stackpack model).
	ClusterName string `mapstructure:"cluster_name"`
}

func createDefaultConfig() *Config {
	return &Config{
		FlushInterval: 60 * time.Second,
		Retention:     15 * time.Minute,
	}
}

func (cfg *Config) Validate() error {
	if cfg.Endpoint == "" {
		return errors.New("endpoint is required")
	}
	if cfg.APIKey == "" {
		return errors.New("api_key is required")
	}
	if cfg.FlushInterval < 10*time.Second {
		return errors.New("flush_interval must be >= 10s")
	}
	if cfg.Retention < cfg.FlushInterval {
		return errors.New("retention must be >= flush_interval")
	}
	return nil
}
