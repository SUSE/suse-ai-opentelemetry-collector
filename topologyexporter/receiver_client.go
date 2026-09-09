package topologyexporter

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
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

func (c *receiverClient) send(ctx context.Context, components []Component, relations []Relation) error {
	payload := NewPayload(c.instance, components, relations)

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	endpoint, err := url.Parse(c.endpoint + "/" + receiverEndpoint)
	if err != nil {
		return errors.New("invalid receiver endpoint")
	}
	query := endpoint.Query()
	query.Set("api_key", c.apiKey)
	endpoint.RawQuery = query.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint.String(), bytes.NewReader(body))
	if err != nil {
		return errors.New("failed to create topology request")
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		// net/http wraps transport failures in a url.Error containing the secret
		// query string. Preserve cancellation/error identity without the URL.
		var urlErr *url.Error
		if errors.As(err, &urlErr) {
			err = urlErr.Err
		}
		return fmt.Errorf("failed to send topology: %w", err)
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("receiver returned status %d", resp.StatusCode)
	}

	slog.Info("topology sent",
		"components", len(components),
		"relations", len(relations),
		"status", resp.StatusCode,
	)
	return nil
}
