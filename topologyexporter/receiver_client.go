package topologyexporter

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
)

const receiverEndpoint = "receiver/stsAgent/intake"

type receiverClient struct {
	endpoint   string
	apiKey     string
	instance   Instance
	httpClient *http.Client
}

func newReceiverClient(endpoint, apiKey string, instance Instance, httpClient *http.Client) *receiverClient {
	return &receiverClient{
		endpoint:   strings.TrimSuffix(endpoint, "/"),
		apiKey:     apiKey,
		instance:   instance,
		httpClient: httpClient,
	}
}

func (c *receiverClient) send(components []Component, relations []Relation) error {
	payload := NewPayload(c.instance, components, relations)

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	url := fmt.Sprintf("%s/%s?api_key=%s", c.endpoint, receiverEndpoint, c.apiKey)
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send topology: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return fmt.Errorf("receiver returned status %d", resp.StatusCode)
	}

	slog.Info("topology sent",
		"components", len(components),
		"relations", len(relations),
		"status", resp.StatusCode,
	)
	return nil
}
