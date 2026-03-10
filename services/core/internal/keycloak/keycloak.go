package keycloak

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"sync"
	"time"

	"github.com/nepornucz/discord-bot-core/internal/config"
)

type cacheEntry struct {
	Groups    []interface{}
	Timestamp time.Time
}

type KeycloakClient struct {
	Config     *config.Config
	Token      string
	TokenMu    sync.RWMutex
	HTTPClient *http.Client
	groupCache sync.Map
	cacheTTL   time.Duration
}

func NewClient(cfg *config.Config) *KeycloakClient {
	return &KeycloakClient{
		Config: cfg,
		HTTPClient: &http.Client{
			Timeout: 10 * time.Second,
		},
		cacheTTL: 5 * time.Minute,
	}
}

func (c *KeycloakClient) getToken() (string, error) {
	c.TokenMu.Lock()
	defer c.TokenMu.Unlock()

	endpoint := fmt.Sprintf("%s/realms/master/protocol/openid-connect/token", c.Config.KCInternalURL)
	data := url.Values{}
	data.Set("grant_type", "password")
	data.Set("client_id", "admin-cli")
	data.Set("username", "admin")
	data.Set("password", c.Config.KCAdminPassword)

	resp, err := c.HTTPClient.PostForm(endpoint, data)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("failed to get token: %s", resp.Status)
	}

	var result struct {
		AccessToken string `json:"access_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", err
	}

	c.Token = result.AccessToken
	return c.Token, nil
}

func (c *KeycloakClient) GetUserGroups(kcUserID string) ([]interface{}, error) {
	if val, ok := c.groupCache.Load(kcUserID); ok {
		entry := val.(cacheEntry)
		if time.Since(entry.Timestamp) < c.cacheTTL {
			return entry.Groups, nil
		}
	}

	c.TokenMu.RLock()
	token := c.Token
	c.TokenMu.RUnlock()

	if token == "" {
		t, err := c.getToken()
		if err != nil {
			return nil, err
		}
		token = t
	}

	endpoint := fmt.Sprintf("%s/admin/realms/nepornu/users/%s/groups", c.Config.KCInternalURL, kcUserID)

	fetchGroups := func(tk string) (*http.Response, error) {
		req, _ := http.NewRequest("GET", endpoint, nil)
		req.Header.Set("Authorization", "Bearer "+tk)
		return c.HTTPClient.Do(req)
	}

	resp, err := fetchGroups(token)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusUnauthorized {
		token, err = c.getToken()
		if err != nil {
			return nil, err
		}
		resp, err = fetchGroups(token)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed to get groups: %s", resp.Status)
	}

	var groups []interface{}
	if err := json.NewDecoder(resp.Body).Decode(&groups); err != nil {
		return nil, err
	}

	c.groupCache.Store(kcUserID, cacheEntry{
		Groups:    groups,
		Timestamp: time.Now(),
	})

	return groups, nil
}
