package topologyexporter

import (
	"errors"
	"net/url"
	"time"

	"go.opentelemetry.io/collector/config/configopaque"
	"go.opentelemetry.io/collector/config/configtls"
)

type Config struct {
	TLS           configtls.ClientConfig `mapstructure:"tls"`
	Endpoint      string                 `mapstructure:"endpoint"`
	APIKey        configopaque.String    `mapstructure:"api_key"`
	Timeout       time.Duration          `mapstructure:"timeout"`
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
		Timeout:       10 * time.Second,
		FlushInterval: 60 * time.Second,
		Retention:     15 * time.Minute,
	}
}

func (cfg *Config) Validate() error {
	if cfg.Endpoint == "" {
		return errors.New("endpoint is required")
	}
	endpoint, err := url.Parse(cfg.Endpoint)
	if err != nil || endpoint.Host == "" || (endpoint.Scheme != "http" && endpoint.Scheme != "https") || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" {
		return errors.New("endpoint must be an absolute HTTP(S) URL without credentials, query parameters, or a fragment")
	}
	if cfg.APIKey == "" {
		return errors.New("api_key is required")
	}
	if cfg.Timeout <= 0 {
		return errors.New("timeout must be positive")
	}
	if cfg.FlushInterval < 10*time.Second {
		return errors.New("flush_interval must be >= 10s")
	}
	if cfg.Retention < cfg.FlushInterval {
		return errors.New("retention must be >= flush_interval")
	}
	return nil
}
